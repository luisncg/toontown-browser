/**
 * Browser entry point for the Open Toontown WebAssembly client.
 *
 * Panda3D's Python task manager intentionally does not own the event loop on
 * Emscripten.  This launcher embeds CPython, registers Panda3D's statically
 * linked extension modules, imports the browser client, and lets the browser
 * drive the Python client from a browser-managed, capped frame loop.
 */

#include <Python.h>
#include <emscripten.h>
#include <stdlib.h>
#include <string.h>

#include "pandabase.h"

extern "C" PyObject *PyInit_core(void);
extern "C" PyObject *PyInit_direct(void);
extern "C" PyObject *PyInit_ode(void);
extern "C" PyObject *PyInit_physics(void);
extern "C" PyObject *PyInit_otp(void);
extern "C" PyObject *PyInit_toontown(void);

extern "C" EXPCL_PANDA_PNMIMAGETYPES void init_libpnmimagetypes(void);
extern "C" void init_libwebgldisplay(void);
extern void init_libpipeline(void);
extern "C" void init_libOpenALAudio(void);

static PyObject *frame_callback = NULL;
static PyObject *mobile_input_callback = NULL;

#define BROWSER_TARGET_FPS 60
#define BROWSER_FRAME_INTERVAL_MS (1000.0 / BROWSER_TARGET_FPS)

static int fps_test_enabled = 0;
static int fps_test_frame_count = 0;
static double fps_test_started_at = 0.0;
static double next_browser_frame_at = -1.0;

extern "C" EMSCRIPTEN_KEEPALIVE int
browser_mouse_look_capture_allowed(void) {
  // Browser Pointer Lock must be requested from the originating click event.
  // Ask the live Python client synchronously whether Panda's MouseWatcher is
  // currently over a DirectGUI region before the browser consumes activation.
  int allowed = 1;
  PyGILState_STATE gil_state = PyGILState_Ensure();
  PyObject *builtins_dict = PyEval_GetBuiltins();
  PyObject *base_object = PyDict_GetItemString(builtins_dict, "base");
  if (base_object != NULL) {
    PyObject *avatar = PyObject_GetAttrString(base_object, "localAvatar");
    if (avatar != NULL) {
      PyObject *result = PyObject_CallMethod(
        avatar, "isExperimentalMouseLookCaptureAllowed", NULL);
      if (result != NULL) {
        const int truth = PyObject_IsTrue(result);
        if (truth >= 0) {
          allowed = truth;
        }
        Py_DECREF(result);
      } else {
        PyErr_Clear();
      }
      Py_DECREF(avatar);
    } else {
      PyErr_Clear();
    }
  }
  PyGILState_Release(gil_state);
  return allowed;
}

extern "C" EMSCRIPTEN_KEEPALIVE int
browser_mobile_action(int action_code, int pressed) {
  if (mobile_input_callback == NULL) {
    return 0;
  }

  int handled = 0;
  PyGILState_STATE gil_state = PyGILState_Ensure();
  PyObject *result = PyObject_CallFunction(
    mobile_input_callback, "ii", action_code, pressed ? 1 : 0);
  if (result != NULL) {
    const int truth = PyObject_IsTrue(result);
    if (truth >= 0) {
      handled = truth;
    }
    Py_DECREF(result);
  } else {
    PyErr_Print();
  }
  PyGILState_Release(gil_state);
  return handled;
}

static PyObject *browser_storage_get_item(PyObject *, PyObject *args) {
  const char *key;
  if (!PyArg_ParseTuple(args, "s", &key)) {
    return NULL;
  }

  char *value = reinterpret_cast<char *>(EM_ASM_PTR({
    try {
      const value = window.localStorage.getItem(UTF8ToString($0));
      if (value === null) return 0;
      const size = lengthBytesUTF8(value) + 1;
      const pointer = _malloc(size);
      stringToUTF8(value, pointer, size);
      return pointer;
    } catch (error) {
      return 0;
    }
  }, key));

  if (value == NULL) {
    Py_RETURN_NONE;
  }

  PyObject *result = PyUnicode_DecodeUTF8(value, strlen(value), "strict");
  free(value);
  return result;
}

static PyObject *browser_runtime_game_server(PyObject *, PyObject *) {
  char *value = reinterpret_cast<char *>(EM_ASM_PTR({
    try {
      const value = window.__toontownGameServer;
      if (typeof value !== "string" || value.length === 0) return 0;
      const size = lengthBytesUTF8(value) + 1;
      const pointer = _malloc(size);
      stringToUTF8(value, pointer, size);
      return pointer;
    } catch (error) {
      return 0;
    }
  }));

  if (value == NULL) {
    Py_RETURN_NONE;
  }

  PyObject *result = PyUnicode_DecodeUTF8(value, strlen(value), "strict");
  free(value);
  return result;
}

static PyObject *browser_storage_set_item(PyObject *, PyObject *args) {
  const char *key;
  const char *value;
  if (!PyArg_ParseTuple(args, "ss", &key, &value)) {
    return NULL;
  }

  const int stored = EM_ASM_INT({
    try {
      window.localStorage.setItem(UTF8ToString($0), UTF8ToString($1));
      return 1;
    } catch (error) {
      return 0;
    }
  }, key, value);
  if (!stored) {
    PyErr_SetString(PyExc_RuntimeError, "Browser local storage is unavailable");
    return NULL;
  }

  Py_RETURN_NONE;
}

static PyObject *browser_pointer_lock_active(PyObject *, PyObject *) {
  const int active = EM_ASM_INT({
    const canvas = document.querySelector("#canvas");
    return canvas !== null && document.pointerLockElement === canvas;
  });
  return PyBool_FromLong(active);
}

static PyObject *browser_pointer_lock_release(PyObject *, PyObject *) {
  const int released = EM_ASM_INT({
    const canvas = document.querySelector("#canvas");
    if (canvas !== null && document.pointerLockElement === canvas) {
      document.exitPointerLock();
      return 1;
    }
    return 0;
  });
  return PyBool_FromLong(released);
}

static PyObject *browser_mobile_controls_visible(PyObject *, PyObject *args) {
  int visible;
  if (!PyArg_ParseTuple(args, "p", &visible)) {
    return NULL;
  }
  EM_ASM({
    window.dispatchEvent(new CustomEvent("toontownmobilecontrols", {
      detail: {visible: Boolean($0)},
    }));
  }, visible);
  Py_RETURN_NONE;
}

static PyObject *browser_mobile_form_get_value(PyObject *, PyObject *args) {
  const char *field;
  if (!PyArg_ParseTuple(args, "s", &field)) {
    return NULL;
  }

  char *value = reinterpret_cast<char *>(EM_ASM_PTR({
    try {
      const controller = window.ToontownMobileForm;
      if (!controller || typeof controller.valueForField !== "function") {
        return 0;
      }
      const value = String(controller.valueForField(UTF8ToString($0)) ?? "");
      const size = lengthBytesUTF8(value) + 1;
      const pointer = _malloc(size);
      stringToUTF8(value, pointer, size);
      return pointer;
    } catch (error) {
      return 0;
    }
  }, field));

  if (value == NULL) {
    Py_RETURN_NONE;
  }

  PyObject *result = PyUnicode_DecodeUTF8(value, strlen(value), "strict");
  free(value);
  return result;
}

static PyObject *browser_mobile_form_set_state(PyObject *, PyObject *args) {
  const char *mode;
  const char *username;
  int interactive;
  if (!PyArg_ParseTuple(args, "ssp", &mode, &username, &interactive)) {
    return NULL;
  }
  EM_ASM({
    window.dispatchEvent(new CustomEvent("toontownmobileform", {
      detail: {
        mode: UTF8ToString($0),
        username: UTF8ToString($1),
        interactive: Boolean($2),
      },
    }));
  }, mode, username, interactive);
  Py_RETURN_NONE;
}

static PyMethodDef browser_storage_methods[] = {
  {"get_runtime_game_server", browser_runtime_game_server, METH_NOARGS,
   "Return the in-memory Astron gateway URL supplied by the browser shell."},
  {"get_item", browser_storage_get_item, METH_VARARGS,
   "Return a browser localStorage value, or None."},
  {"set_item", browser_storage_set_item, METH_VARARGS,
   "Store a browser localStorage value."},
  {"is_pointer_locked", browser_pointer_lock_active, METH_NOARGS,
   "Return whether the game canvas owns browser Pointer Lock."},
  {"exit_pointer_lock", browser_pointer_lock_release, METH_NOARGS,
   "Release browser Pointer Lock from the game canvas."},
  {"set_mobile_controls_visible", browser_mobile_controls_visible, METH_VARARGS,
   "Show or hide the portrait touch-control deck."},
  {"get_mobile_form_value", browser_mobile_form_get_value, METH_VARARGS,
   "Return an in-memory native mobile form value without persisting it."},
  {"set_mobile_form_state", browser_mobile_form_set_state, METH_VARARGS,
   "Show or hide native mobile login form proxies."},
  {NULL, NULL, 0, NULL},
};

static PyModuleDef browser_storage_module = {
  PyModuleDef_HEAD_INIT,
  "browser_storage",
  "Minimal browser-local persistence for the embedded Python client.",
  -1,
  browser_storage_methods,
};

static int install_browser_storage_module(void) {
  PyObject *module = PyModule_Create(&browser_storage_module);
  if (module == NULL) {
    PyErr_Print();
    return 0;
  }

  const int result = PyDict_SetItemString(
    PyImport_GetModuleDict(), "browser_storage", module);
  Py_DECREF(module);
  if (result < 0) {
    PyErr_Print();
    return 0;
  }
  return 1;
}

static PyObject *browser_assets_request_phase(PyObject *, PyObject *args) {
  const char *phase;
  if (!PyArg_ParseTuple(args, "s", &phase)) {
    return NULL;
  }
  const int accepted = EM_ASM_INT({
    const loader = window.ToontownAssetLoader;
    if (!loader) return 0;
    try {
      loader.requestPhase(UTF8ToString($0)).catch(() => {});
      return 1;
    } catch (error) {
      console.error("[Toontown phases] request failed", error);
      return 0;
    }
  }, phase);
  return PyBool_FromLong(accepted);
}

static PyObject *browser_assets_prepare_playground(PyObject *, PyObject *) {
  const int accepted = EM_ASM_INT({
    const loader = window.ToontownAssetLoader;
    if (!loader) return 0;
    loader.preparePlayground();
    return 1;
  });
  return PyBool_FromLong(accepted);
}

static PyObject *browser_assets_start_background(PyObject *, PyObject *) {
  const int accepted = EM_ASM_INT({
    const loader = window.ToontownAssetLoader;
    if (!loader) return 0;
    loader.startBackgroundDownloads();
    return 1;
  });
  return PyBool_FromLong(accepted);
}

static PyObject *browser_assets_phase_state(PyObject *, PyObject *args) {
  const char *phase;
  if (!PyArg_ParseTuple(args, "s", &phase)) {
    return NULL;
  }
  const int state = EM_ASM_INT({
    const loader = window.ToontownAssetLoader;
    return loader ? loader.phaseState(UTF8ToString($0)) : 0;
  }, phase);
  return PyLong_FromLong(state);
}

static PyObject *browser_assets_phase_progress(PyObject *, PyObject *args) {
  const char *phase;
  if (!PyArg_ParseTuple(args, "s", &phase)) {
    return NULL;
  }
  const int progress = EM_ASM_INT({
    const loader = window.ToontownAssetLoader;
    return loader ? loader.phaseProgress(UTF8ToString($0)) : 0;
  }, phase);
  return PyLong_FromLong(progress);
}

static PyMethodDef browser_assets_methods[] = {
  {"request_phase", browser_assets_request_phase, METH_VARARGS,
   "Request a streamed Toontown resource phase."},
  {"prepare_playground", browser_assets_prepare_playground, METH_NOARGS,
   "Load the phases required for initial playground entry."},
  {"start_background", browser_assets_start_background, METH_NOARGS,
   "Download all remaining Toontown phases in the background."},
  {"phase_state", browser_assets_phase_state, METH_VARARGS,
   "Return 0 idle, 1 loading, 2 ready, or 3 error for a phase."},
  {"phase_progress", browser_assets_phase_progress, METH_VARARGS,
   "Return an integer download percentage for a phase."},
  {NULL, NULL, 0, NULL},
};

static PyModuleDef browser_assets_module = {
  PyModuleDef_HEAD_INIT,
  "browser_assets",
  "Bridge between the preserved launcher and browser phase packages.",
  -1,
  browser_assets_methods,
};

static int install_browser_assets_module(void) {
  PyObject *module = PyModule_Create(&browser_assets_module);
  if (module == NULL) {
    PyErr_Print();
    return 0;
  }
  const int result = PyDict_SetItemString(
    PyImport_GetModuleDict(), "browser_assets", module);
  Py_DECREF(module);
  if (result < 0) {
    PyErr_Print();
    return 0;
  }
  return 1;
}

static void browser_status(const char *phase, const char *message) {
  EM_ASM({
    const phase = UTF8ToString($0);
    const message = UTF8ToString($1);
    window.dispatchEvent(new CustomEvent("toontownwasmstatus", {
      detail: { phase, message }
    }));
  }, phase, message);
}

static int browser_network_test_requested(void) {
  return EM_ASM_INT({
    return new URLSearchParams(window.location.search).get("network-test") === "1";
  });
}

static int browser_input_test_requested(void) {
  return EM_ASM_INT({
    return new URLSearchParams(window.location.search).get("input-test") === "1";
  });
}

static int browser_alpha_test_requested(void) {
  return EM_ASM_INT({
    return new URLSearchParams(window.location.search).get("alpha-test") === "1";
  });
}

static int browser_tree_alpha_test_requested(void) {
  return EM_ASM_INT({
    return new URLSearchParams(window.location.search).get("tree-alpha-test") === "1";
  });
}

static int browser_reactive_test_requested(void) {
  return EM_ASM_INT({
    return new URLSearchParams(window.location.search).get("reactive-test") === "1";
  });
}

static int browser_audio_test_requested(void) {
  return EM_ASM_INT({
    return new URLSearchParams(window.location.search).get("audio-test") === "1";
  });
}

static int browser_fps_test_requested(void) {
  return EM_ASM_INT({
    return new URLSearchParams(window.location.search).get("fps-test") === "1";
  });
}

static int install_module(PyObject *package_dict, PyObject *sys_modules,
                          const char *name, PyObject *module) {
  if (module == NULL) {
    PyErr_Print();
    return 0;
  }

  if (PyDict_SetItemString(package_dict, name, module) < 0) {
    PyErr_Print();
    Py_DECREF(module);
    return 0;
  }

  char qualified_name[128];
  PyOS_snprintf(qualified_name, sizeof(qualified_name), "panda3d.%s", name);
  if (PyDict_SetItemString(sys_modules, qualified_name, module) < 0) {
    PyErr_Print();
    Py_DECREF(module);
    return 0;
  }

  Py_DECREF(module);
  return 1;
}

static int install_panda3d_modules(void) {
  PyObject *package = PyImport_ImportModule("panda3d");
  if (package == NULL) {
    PyErr_Print();
    return 0;
  }

  PyObject *package_dict = PyModule_GetDict(package);
  PyObject *sys_modules = PyImport_GetModuleDict();

  const int success =
    install_module(package_dict, sys_modules, "core", PyInit_core()) &&
    install_module(package_dict, sys_modules, "direct", PyInit_direct()) &&
    install_module(package_dict, sys_modules, "ode", PyInit_ode()) &&
    install_module(package_dict, sys_modules, "physics", PyInit_physics()) &&
    install_module(package_dict, sys_modules, "otp", PyInit_otp()) &&
    install_module(package_dict, sys_modules, "toontown", PyInit_toontown());

  Py_DECREF(package);
  return success;
}

static void run_frame(void) {
  const double frame_started_at = emscripten_get_now();
  PyObject *result = PyObject_CallNoArgs(frame_callback);
  const double frame_duration_ms = emscripten_get_now() - frame_started_at;
  if (frame_duration_ms >= 100.0) {
    EM_ASM({
      console.log(
        "[BrowserPerformanceFrameCall] " + Math.round($0)
      );
    }, frame_duration_ms);
  }
  if (result != NULL) {
    Py_DECREF(result);

    if (fps_test_enabled) {
      const double now = emscripten_get_now();
      if (fps_test_frame_count == 0) {
        fps_test_started_at = now;
      }
      ++fps_test_frame_count;

      const double elapsed = now - fps_test_started_at;
      if (elapsed >= 2500.0) {
        const double measured_fps =
          (fps_test_frame_count - 1) * 1000.0 / elapsed;
        EM_ASM({
          window.__openToontownFpsTest = ({
            targetFps: $0,
            measuredFps: $1,
            frameCount: $2,
            elapsedMs: $3,
          });
        }, BROWSER_TARGET_FPS, measured_fps, fps_test_frame_count, elapsed);
        fps_test_enabled = 0;
      }
    }
    return;
  }

  PyErr_Print();
  browser_status("error", "The Python frame callback failed. See the browser console.");
  emscripten_cancel_main_loop();
}

static void run_capped_frame(void) {
  const double now = emscripten_get_now();
  if (next_browser_frame_at < 0.0) {
    next_browser_frame_at = now;
  }

  // Stay synchronized to requestAnimationFrame, but skip excess callbacks on
  // high-refresh-rate displays.  Retaining the target phase lets 120/144 Hz
  // panels average 60 game frames instead of drifting down to a divisor.
  if (now + 0.25 < next_browser_frame_at) {
    return;
  }

  run_frame();
  next_browser_frame_at += BROWSER_FRAME_INTERVAL_MS;
  if (next_browser_frame_at <= now) {
    // Do not try to catch up after a suspended/backgrounded tab.
    next_browser_frame_at = now + BROWSER_FRAME_INTERVAL_MS;
  }
}

static int initialize_python(void) {
  PyStatus status;
  PyConfig config;
  PyConfig_InitPythonConfig(&config);

  config.parse_argv = 0;
  config.install_signal_handlers = 0;
  config.write_bytecode = 0;

  status = PyConfig_SetBytesString(&config, &config.home, "/python");
  if (PyStatus_Exception(status)) {
    goto exception;
  }

  status = PyConfig_SetBytesString(&config, &config.program_name,
                                   "/app/open-toontown-wasm");
  if (PyStatus_Exception(status)) {
    goto exception;
  }

  status = Py_InitializeFromConfig(&config);
  if (PyStatus_Exception(status)) {
    goto exception;
  }
  PyConfig_Clear(&config);
  return 1;

exception:
  PyConfig_Clear(&config);
  if (PyStatus_IsExit(status)) {
    return 0;
  }
  Py_ExitStatusException(status);
  return 0;
}

int main(void) {
  browser_status("python", "Starting the embedded Python runtime…");

  if (!initialize_python()) {
    browser_status("error", "CPython could not be initialized.");
    return 1;
  }

  if (PyRun_SimpleString(
        "import sys\n"
        "sys.path.insert(0, '/app')\n"
        "sys.path.insert(0, '/game')\n"
        "sys.path.insert(0, '/engine')\n") != 0) {
    PyErr_Print();
    browser_status("error", "The browser Python paths could not be configured.");
    return 1;
  }

  if (!install_browser_storage_module()) {
    browser_status("error", "Browser settings storage could not be initialized.");
    return 1;
  }
  if (!install_browser_assets_module()) {
    browser_status("error", "Browser phase streaming could not be initialized.");
    return 1;
  }

  init_libpnmimagetypes();
  init_libpipeline();
  init_libwebgldisplay();
  init_libOpenALAudio();

  if (!install_panda3d_modules()) {
    browser_status("error", "The Panda3D extension modules could not be registered.");
    return 1;
  }

  browser_status("engine", "Panda3D loaded. Creating the WebGL scene…");

  const char *client_module_name;
  if (browser_reactive_test_requested()) {
    client_module_name = "browser_reactive_test";
  } else if (browser_tree_alpha_test_requested()) {
    client_module_name = "browser_tree_alpha_test";
  } else if (browser_alpha_test_requested()) {
    client_module_name = "browser_alpha_test";
  } else if (browser_network_test_requested()) {
    client_module_name = "browser_network_test";
  } else if (browser_input_test_requested()) {
    client_module_name = "browser_input_test";
  } else if (browser_audio_test_requested()) {
    client_module_name = "browser_audio_test";
#ifdef OPEN_TOONTOWN_GAME_BUILD
  } else {
    client_module_name = "browser_game";
#else
  } else {
    client_module_name = "browser_client";
#endif
  }
  PyObject *client_module = PyImport_ImportModule(client_module_name);
  if (client_module == NULL) {
    PyErr_Print();
    browser_status("error", "The browser client bootstrap failed.");
    return 1;
  }

  frame_callback = PyObject_GetAttrString(client_module, "frame");
  mobile_input_callback = PyObject_GetAttrString(client_module, "mobile_input");
  if (mobile_input_callback == NULL) {
    PyErr_Clear();
  } else if (!PyCallable_Check(mobile_input_callback)) {
    Py_CLEAR(mobile_input_callback);
  }
  Py_DECREF(client_module);
  if (frame_callback == NULL || !PyCallable_Check(frame_callback)) {
    PyErr_Print();
    browser_status("error", "The browser client did not expose a frame callback.");
    return 1;
  }

  browser_status("ready", "Open Toontown's Panda3D runtime is drawing through WebGL.");
  fps_test_enabled = browser_fps_test_requested();
  emscripten_set_main_loop(run_capped_frame, 0, 1);
  return 0;
}
