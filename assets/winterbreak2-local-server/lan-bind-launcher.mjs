import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import util from "node:util";
import { pathToFileURL } from "node:url";

const bindAddress = process.env.WB2_BIND_ADDRESS;
const entryPath = process.env.WB2_ENTRY_PATH;
const logPath = process.env.WB2_BOUNDED_LOG_PATH;
const requestedPort = Number.parseInt(process.env.PORT || "", 10);
const maxLogBytes = Number.parseInt(process.env.WB2_MAX_LOG_BYTES || "262144", 10);

if (!net.isIPv4(bindAddress || "")) {
  throw new Error("WB2_BIND_ADDRESS must be an IPv4 address");
}
if (!entryPath || !path.isAbsolute(entryPath)) {
  throw new Error("WB2_ENTRY_PATH must be absolute");
}
if (!logPath || !path.isAbsolute(logPath)) {
  throw new Error("WB2_BOUNDED_LOG_PATH must be absolute");
}
if (!Number.isSafeInteger(requestedPort) || requestedPort < 1 || requestedPort > 65535) {
  throw new Error("PORT must be an integer between 1 and 65535");
}
if (!Number.isSafeInteger(maxLogBytes) || maxLogBytes < 65536 || maxLogBytes > 1048576) {
  throw new Error("WB2_MAX_LOG_BYTES must be between 65536 and 1048576");
}

fs.mkdirSync(path.dirname(logPath), { recursive: true });

function appendBounded(level, args) {
  let line = `${new Date().toISOString()} ${level} ${util.format(...args)}\n`;
  let bytes = Buffer.from(line, "utf8");
  if (bytes.length > Math.floor(maxLogBytes / 2)) {
    bytes = bytes.subarray(0, Math.floor(maxLogBytes / 2));
  }
  try {
    const size = fs.existsSync(logPath) ? fs.statSync(logPath).size : 0;
    if (size + bytes.length > maxLogBytes) {
      const previous = `${logPath}.previous`;
      fs.rmSync(previous, { force: true });
      if (fs.existsSync(logPath)) fs.renameSync(logPath, previous);
    }
    fs.appendFileSync(logPath, bytes);
  } catch {
    // Logging must never change or broaden the server's network behavior.
  }
}

console.log = (...args) => appendBounded("INFO", args);
console.info = (...args) => appendBounded("INFO", args);
console.warn = (...args) => appendBounded("WARN", args);
console.error = (...args) => appendBounded("ERROR", args);
process.on("uncaughtException", (error) => {
  appendBounded("FATAL", [error]);
  process.exit(1);
});
process.on("unhandledRejection", (reason) => {
  appendBounded("FATAL", [reason]);
  process.exit(1);
});

const originalListen = net.Server.prototype.listen;
net.Server.prototype.listen = function (...args) {
  const port = typeof args[0] === "number"
    ? args[0]
    : (/^[0-9]+$/.test(args[0] || "") ? Number.parseInt(args[0], 10) : NaN);
  if (!Number.isSafeInteger(port) || port !== requestedPort) {
    throw new Error("The pinned WinterBreak2 server changed its listen signature");
  }
  args[0] = port;
  if (typeof args[1] === "function" || args.length === 1) {
    args.splice(1, 0, bindAddress);
  } else if (typeof args[1] === "string") {
    args[1] = bindAddress;
  } else {
    throw new Error("The pinned WinterBreak2 server changed its listen arguments");
  }
  return originalListen.apply(this, args);
};

await import(pathToFileURL(entryPath).href);
