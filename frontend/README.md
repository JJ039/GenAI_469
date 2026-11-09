# Bank crisis dashboard

See the [project README](../README.md) for credentials, model settings and the
complete research evaluation command.

From this folder, start Flask with the project virtual environment:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe server.py
```

In another terminal in this folder:

```powershell
npm install
npm start
```

Open http://localhost:3000. The API uses port 5000. Baseline and multi-agent final
decisions, scores, traces and simulated Treasury outcomes are shown separately.
The dashboard uses the same engine and evaluator as the batch runner.

```powershell
npm test -- --watchAll=false --runInBand
npm run build
```
