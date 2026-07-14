/* global process, console, URL */
import { createReadStream } from 'node:fs'
import { stat } from 'node:fs/promises'
import { createServer } from 'node:http'
import { extname, resolve, sep } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = resolve(fileURLToPath(new URL('../dist/', import.meta.url)))
const mimeTypes = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.webp': 'image/webp',
  '.woff2': 'font/woff2',
}

const sendFile = async (path, response) => {
  const metadata = await stat(path)
  if (!metadata.isFile()) throw new Error('not a file')
  response.writeHead(200, {
    'Cache-Control': 'no-store',
    'Content-Length': metadata.size,
    'Content-Type': mimeTypes[extname(path).toLowerCase()] || 'application/octet-stream',
  })
  createReadStream(path).pipe(response)
}

export function startUiSmokeServer(port = Number(process.env.UI_SMOKE_PORT || 6021)) {
  const server = createServer(async (request, response) => {
    try {
      const requestUrl = new URL(request.url || '/', 'http://127.0.0.1')
      const relativePath = decodeURIComponent(requestUrl.pathname).replace(/^\/+/, '')
      const candidate = resolve(root, relativePath || 'index.html')
      if (candidate !== root && !candidate.startsWith(`${root}${sep}`)) {
        response.writeHead(403).end('Forbidden')
        return
      }

      try {
        await sendFile(candidate, response)
      } catch {
        await sendFile(resolve(root, 'index.html'), response)
      }
    } catch {
      response.writeHead(400).end('Bad Request')
    }
  })

  return new Promise((resolvePromise, rejectPromise) => {
    server.once('error', rejectPromise)
    server.listen(port, '127.0.0.1', () => {
      server.off('error', rejectPromise)
      resolvePromise(server)
    })
  })
}

const invokedDirectly = process.argv[1]
  ? pathToFileURL(resolve(process.argv[1])).href === import.meta.url
  : false

if (invokedDirectly) {
  const port = Number(process.argv[2] || process.env.UI_SMOKE_PORT || 6021)
  await startUiSmokeServer(port)
  console.log(`UI smoke server listening on http://127.0.0.1:${port}`)
}
