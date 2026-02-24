const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { URL } = require('node:url');
const { parseReservationRequest } = require('./reservationParser');

const host = process.env.HOST || '127.0.0.1';
const port = Number(process.env.PORT || 3000);

const workspaceRoot = path.resolve(__dirname, '..');
const bridgeScript = path.join(workspaceRoot, 'scripts', 'node_python_bridge.py');
const defaultPythonExe = path.join(workspaceRoot, '.venv', 'Scripts', 'python.exe');
const pythonExe = process.env.PYTHON_EXE || (fs.existsSync(defaultPythonExe) ? defaultPythonExe : 'python');

function invokePythonBridge(action, payload = {}) {
  const mergedPythonPath = process.env.PYTHONPATH
    ? `${workspaceRoot}${path.delimiter}${process.env.PYTHONPATH}`
    : workspaceRoot;

  const result = spawnSync(pythonExe, [bridgeScript, action], {
    input: JSON.stringify(payload),
    encoding: 'utf-8',
    cwd: workspaceRoot,
    timeout: 30_000,
    env: {
      ...process.env,
      PYTHONPATH: mergedPythonPath,
      PYTHONIOENCODING: 'utf-8',
      PYTHONUTF8: '1',
    },
  });

  if (result.error) {
    throw new Error(`python bridge execution failed: ${result.error.message}`);
  }

  if (result.status !== 0) {
    const stderr = (result.stderr || '').trim();
    throw new Error(stderr || `python bridge failed with exit code ${result.status}`);
  }

  const stdout = (result.stdout || '').trim();
  if (!stdout) {
    throw new Error('python bridge returned empty output');
  }

  let parsed;
  try {
    parsed = JSON.parse(stdout);
  } catch {
    throw new Error(`python bridge returned non-JSON output: ${stdout}`);
  }

  if (typeof parsed.status !== 'number') {
    throw new Error('python bridge output missing status');
  }

  return parsed;
}

function renderNodeFrontendPage() {
  const templatePath = path.join(workspaceRoot, 'templates', 'index.html');
  const html = fs.readFileSync(templatePath, 'utf-8');
  return html.replace(
    '<h1 class="title">스마트 공용 자원 예약 시스템 (자연어 · Python Frontend)</h1>',
    '<h1 class="title">스마트 공용 자원 예약 시스템 (자연어 · Node.js Frontend)</h1>'
  );
}

function renderTestPage() {
  return `<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Node 예약 파서 테스트</title>
    <style>
      body { font-family: Arial, sans-serif; margin: 24px; background: #f6f8fc; color: #1f2a44; }
      .card { max-width: 860px; background: #fff; border: 1px solid #d8deea; border-radius: 12px; padding: 16px; }
      input, button { font-size: 14px; }
      input { width: calc(100% - 120px); padding: 10px; border: 1px solid #d8deea; border-radius: 8px; }
      button { width: 100px; padding: 10px; border: none; border-radius: 8px; background: #2f6bff; color: #fff; cursor: pointer; }
      pre { margin-top: 14px; padding: 12px; border-radius: 8px; background: #0f172a; color: #e2e8f0; overflow: auto; }
      .hint { color: #5a6785; margin-bottom: 10px; }
      .row { display: flex; gap: 10px; }
    </style>
  </head>
  <body>
    <div class="card">
      <h2>Node.js 예약 파서 테스트 페이지</h2>
      <p class="hint">예시: 회의실1 2026-02-25 10:07~11:01 예약</p>
      <div class="row">
        <input id="text" value="회의실1 2026-02-25 10:07~11:01 예약" />
        <button id="parseBtn" type="button">파싱</button>
      </div>
      <pre id="result">아직 요청하지 않았습니다.</pre>
    </div>
    <script>
      const textInput = document.getElementById('text');
      const result = document.getElementById('result');
      const parseBtn = document.getElementById('parseBtn');

      async function parseText() {
        const text = textInput.value.trim();
        if (!text) {
          result.textContent = '입력 문장을 넣어주세요.';
          return;
        }

        try {
          const response = await fetch('/parse', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text }),
          });
          const payload = await response.json();
          result.textContent = JSON.stringify(payload, null, 2);
        } catch (error) {
          result.textContent = '요청 실패: ' + (error?.message || String(error));
        }
      }

      parseBtn.addEventListener('click', parseText);
      textInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
          parseText();
        }
      });
    </script>
  </body>
</html>`;
}

function sendJson(res, statusCode, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  });
  res.end(body);
}

function sendHtml(res, statusCode, html) {
  res.writeHead(statusCode, {
    'Content-Type': 'text/html; charset=utf-8',
    'Content-Length': Buffer.byteLength(html),
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  });
  res.end(html);
}

function collectBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk;
      if (body.length > 1_000_000) {
        reject(new Error('Request body too large'));
        req.destroy();
      }
    });
    req.on('end', () => resolve(body));
    req.on('error', reject);
  });
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === 'OPTIONS') {
      res.writeHead(204, {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
      });
      res.end();
      return;
    }

    const requestUrl = new URL(req.url || '/', `http://${host}:${port}`);

    if (req.method === 'GET' && requestUrl.pathname === '/') {
      sendHtml(res, 200, renderNodeFrontendPage());
      return;
    }

    if (req.method === 'GET' && requestUrl.pathname === '/api/schedule') {
      const period = (requestUrl.searchParams.get('period') || 'day').toLowerCase();
      const bridged = invokePythonBridge('schedule', { period });
      sendJson(res, bridged.status, bridged.json || {});
      return;
    }

    if (req.method === 'POST' && requestUrl.pathname === '/api/reserve/options') {
      const rawBody = await collectBody(req);
      let payload = {};
      try {
        payload = JSON.parse(rawBody || '{}');
      } catch {
        sendJson(res, 400, { ok: false, message: 'Invalid JSON body' });
        return;
      }

      const bridged = invokePythonBridge('options', {
        text: String(payload.text || ''),
      });
      sendJson(res, bridged.status, bridged.json || {});
      return;
    }

    if (req.method === 'POST' && requestUrl.pathname === '/api/reserve/commit') {
      const rawBody = await collectBody(req);
      let payload = {};
      try {
        payload = JSON.parse(rawBody || '{}');
      } catch {
        sendJson(res, 400, { ok: false, message: 'Invalid JSON body' });
        return;
      }

      const bridged = invokePythonBridge('commit', {
        text: String(payload.text || ''),
        option: typeof payload.option === 'object' && payload.option ? payload.option : {},
      });
      sendJson(res, bridged.status, bridged.json || {});
      return;
    }

    if (req.method === 'GET' && requestUrl.pathname === '/health') {
      sendJson(res, 200, { ok: true, service: 'reservation-parser-node', host, port });
      return;
    }

    if (requestUrl.pathname === '/parse') {
      if (req.method === 'GET') {
        const text = (requestUrl.searchParams.get('text') || '').trim();
        if (!text) {
          sendJson(res, 400, { ok: false, message: 'query parameter text is required' });
          return;
        }

        const parsed = parseReservationRequest(text);
        sendJson(res, 200, {
          ok: true,
          parsed: {
            resource: parsed.resource,
            start: parsed.start.toISOString(),
            end: parsed.end.toISOString(),
            rawText: parsed.rawText,
          },
        });
        return;
      }

      if (req.method === 'POST') {
        const rawBody = await collectBody(req);
        let payload;
        try {
          payload = JSON.parse(rawBody || '{}');
        } catch {
          sendJson(res, 400, { ok: false, message: 'Invalid JSON body' });
          return;
        }

        const text = String(payload.text || '').trim();
        if (!text) {
          sendJson(res, 400, { ok: false, message: 'body.text is required' });
          return;
        }

        const parsed = parseReservationRequest(text);
        sendJson(res, 200, {
          ok: true,
          parsed: {
            resource: parsed.resource,
            start: parsed.start.toISOString(),
            end: parsed.end.toISOString(),
            rawText: parsed.rawText,
          },
        });
        return;
      }
    }

    sendJson(res, 404, { ok: false, message: 'Not found' });
  } catch (error) {
    sendJson(res, 400, { ok: false, message: error.message || 'Request failed' });
  }
});

server.listen(port, host, () => {
  console.log(`[node-server] listening on http://${host}:${port}`);
  console.log('[node-server] endpoints: GET /, GET /health, GET/POST /parse, GET /api/schedule, POST /api/reserve/options, POST /api/reserve/commit');
});
