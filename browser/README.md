# Open Toontown in WebAssembly

This port runs the real Open Toontown Python client in a browser with Panda3D,
CPython, ODE, and the custom OTP/Toontown engine modules compiled to WebAssembly.
Astron, UberDOG, and the AI district stay native and run locally as servers.

## Architecture

```text
Browser
  Open Toontown Python + CPython 3.12.8 + Panda3D WebGL (WASM)
       |
       | binary WebSocket (local ws:// or production same-origin wss://)
       v
Loopback WebSocket gateway
       |
       | Astron length-prefixed TCP datagrams
       v
Astron client agent :7198 -> UberDOG + AI district
```

The gateway exposes one route, accepts binary messages only, verifies the
browser origin, targets loopback only, and enforces payload, connection,
traffic, idle, queue, and backpressure limits. In production, a new connection
also requires an opaque five-minute gateway lease issued by the verified web
origin. The encrypted lease binds the bootstrap session, server-generated
resume token, browser identity, client address, and exact origin. A retained
mobile session may reconnect only with its original session/browser identity
during the existing bounded resume window.

Production Caddy accepts application traffic only from Cloudflare's published
networks and forwards a sanitized client address to both the web origin and
gateway. Direct-to-origin HTTPS receives `403`; Astron, the gateway, and the
web process remain on loopback.

## Production dependency boundary

Browser-delivered WASM and assets cannot be made impossible for an authorized
player to capture. Instead, the production boundary makes those captured bytes
non-operational away from the real service:

- anonymous browsers cannot fetch the protected runtime or private R2 assets;
- verified asset requests use opaque, session-bound, short-lived Worker
  tickets and a private manifest that never reaches the browser;
- the browser cannot choose or mint production transport credentials;
- the dedicated web origin issues an encrypted gateway lease only after
  verification, and the gateway independently validates every new session;
- the gateway alone can reach the loopback Astron client agent;
- accounts and authoritative gameplay mutations remain on the native backend;
- `frame-ancestors 'none'` and `X-Frame-Options: DENY` prevent another site
  from embedding the live game as its own frontend.

Client-side hostname checks and periodic WASM phone-home checks are not treated
as security boundaries because a copied client can patch them.

## Pinned sources

- Emscripten `4.0.2`
- CPython `3.12.8`, target `emscripten-browser`
- Open Toontown Panda3D fork `06615744481946654610833679a0893589114504`
- ODE fork `bcfb66cd5e18e32e27cfaae3651ead930bbcda13`
- Open Toontown resources `d8c73a9978633979ddf2ef8813f0152037a0d978`

The toolchain, resource checkout, build directories, and browser distribution
are ignored by Git. No GitHub Actions are used; every build and check runs
locally.

## macOS setup and build

Install the native build dependencies once:

```bash
brew install bison cmake flex ode python@3.12
npm install
```

Then build the WASM engine, native server engine, and complete browser client:

```bash
npm run build:toolchain
npm run build:server
npm run build:game
```

`npm run build:wasm` produces a small procedural WebGL proof without the game
resources. `npm run build:game` fetches the pinned resources checkout and
produces the complete release client in `dist-web/`. Release builds remove the
direct loopback Astron development path and require the signed browser gateway.
For an explicitly local build that can connect directly to the loopback Astron
gateway, use `npm run build:game:debug`; that script enables the build-time
`--local-astron-development` flag.

The current release build transfers about 63 MiB on a cold start after HTTP
compression. It blocks only on the engine, login/Pick-a-Toon resources, and the
early-game core of phase 3.5. Phase 4 is fetched when a Toon enters the game;
later phases and phase 3.5's optional news models continue in the background.
Each heavy response is encrypted into independently authenticated 4 MiB chunks
in IndexedDB, so a warm visit does not download it again. The AES-GCM device key
is non-extractable; browsers without WebCrypto or IndexedDB fall back to the
network instead of writing a plaintext asset cache.

## Run

```bash
npm start
```

This starts Astron, UberDOG, the `Toon Valley` AI district, the constrained
WebSocket gateway, and the static browser server. It opens
<http://127.0.0.1:8180> automatically. Press Ctrl-C to stop only the processes
started by that command. Logs are written to `.build-wasm/logs/`.

Panda3D's OpenAL plugin maps to Web Audio in the Emscripten build. Browsers
start that context suspended; the first click or key press on the game unlocks
music and sound effects.

The Shticker Book's Options page includes a native `Advanced` tab for rebinding
Move Forward, Move Backward, Turn Left, Turn Right, Sprint, and Jump. Sprint
increases forward movement by 50% while held, eases the run animation to 1.2x,
widens the camera by 6 degrees, and defaults to Shift. Bindings reject duplicates
and unsupported keys, update the live Panda3D InputState controls, and persist
with the rest of the browser settings in `localStorage`. Reset Defaults restores
the original arrow-key, Shift, and Space layout. Fresh browser profiles start at
1024x768; a previously saved resolution remains authoritative.

Advanced > Gameplay also includes an opt-in experimental Mouse Steering mode.
During ordinary walk gameplay, click the canvas to capture the pointer and move
the mouse horizontally to turn the Toon; Esc, menus, and non-walk control modes
release it. Keyboard turning remains active as a fallback.

Street Cog Buildings use the classic one-to-five floors and one-to-four Toons.
Mega voting, recruitment, yellow dots, signs, and Mega encounters are retired.
Their old distributed-schema fields remain reserved and inert to preserve
protocol compatibility; they do not enable any gameplay feature.

For camera authoring, press Shift+F8 during normal walk gameplay to enter the POV Free
Camera Lab. WASD flies, Q/E moves vertically, Shift boosts speed, the mouse or
arrow keys look around, the wheel changes FOV, and R returns to the entry view.
The on-screen panel reports world and Toon-relative position/orientation plus a
ten-unit look-at point. Press C to copy the exact `TOONTOWN_POV` record, then F8
to restore the normal Toon camera with Shift+F8.

The stack uses these loopback ports:

| Port | Service |
| ---: | --- |
| 7197 | Astron event logger |
| 7198 | Astron client agent |
| 7199 | Astron message director |
| 7200 | Browser WebSocket gateway |
| 8180 | Browser client and resource server |

The checked-in `astron/darwin/astrond` binary is an Intel macOS build and runs
under Rosetta on Apple Silicon. Other operating systems need the matching
Astron executable and a native Panda3D server build for that platform.

## Checks

With the local stack running:

```bash
npm run test:gateway
npm run test:gateway-bootstrap
npm run test:gateway-lease
npm run test:audio
npm run test:advanced
npm run test:browser
npm run test:focus
npm run test:fps
npm run test:go-home
npm run test:keybinds
npm run test:login
npm run test:mega-native
npm run test:secure-asset-cache
npm run test:asset-worker
npm run test:server-authority
npm run test:browser-network
npm run test:server
```

`test:browser` uses headless Chromium and verifies WebGL rendering, runtime
readiness, response status, failed requests, console errors, and page errors.
`test:audio` loads the actual title music through Panda3D's OpenAL manager,
click-unlocks the browser audio policy, and verifies a running Web Audio
context.
`test:advanced` logs a real Toon into the playground, renders the Advanced
Settings page, remaps Move Forward, rejects a duplicate, and resets defaults.
`test:focus` blurs and refocuses the canvas twice, sends an arrow key after
each return, and verifies that both events reach Panda3D without scrolling the
page.
`test:fps` measures the browser-managed Panda3D loop for 2.5 seconds and
verifies that the full WebAssembly client is capped at 60 FPS.
`test:keybinds` verifies that a persisted W binding drives Panda3D's real
`InputState-forward` while Up Arrow no longer does, and that Shift drives both
the pressed and released states of `InputState-sprint`.
`test:login` enters the isolated local `wasmbrowsersmoke` account through the
real browser transport and verifies that the game advances beyond login.
`test:browser-network` verifies a live CConnectionRepository-to-Astron round
trip through the WebSocket gateway. `test:gateway` separately checks exact
binary framing against an isolated fake Astron endpoint.
`test:server` verifies that the native engine can parse the tutorial DNA and
load both its HTTP and ODE modules.

Local development can still use the bundled developer account path. Production
uses server-side password credentials and rate limiting, and the important new
gameplay mutations are covered by the server-authority contract suite.
