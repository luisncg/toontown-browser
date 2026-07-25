import { createServer } from "node:net";

const server = createServer((socket) => {
  let buffer = Buffer.alloc(0);
  socket.on("data", (chunk) => {
    buffer = buffer.length ? Buffer.concat([buffer, chunk]) : chunk;
    while (buffer.length >= 2) {
      const length = buffer.readUInt16LE(0);
      if (length === 0 || length > 65_535) {
        socket.destroy();
        return;
      }
      if (buffer.length < length + 2) return;

      const payload = buffer.subarray(2, length + 2);
      buffer = buffer.subarray(length + 2);
      if (payload.toString() !== "browser-to-astron") {
        socket.destroy();
        return;
      }

      const response = Buffer.from("astron-to-browser");
      const framed = Buffer.allocUnsafe(response.length + 2);
      framed.writeUInt16LE(response.length, 0);
      response.copy(framed, 2);
      socket.write(framed);
    }
  });
});

server.listen(17198, "127.0.0.1", () => {
  console.log("Fake Astron server: 127.0.0.1:17198");
});
