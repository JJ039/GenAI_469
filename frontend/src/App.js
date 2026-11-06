import React, { useState, useEffect } from 'react';

function App() {
  const [scenarios, setScenarios] = useState([]);
  const [selected, setSelected] = useState("");
  const [progress, setProgress] = useState(null);
  const [result, setResult] = useState(null);
  const [trace, setTrace] = useState([]);
  const [currentStage, setCurrentStage] = useState(0);
  const [taskId, setTaskId] = useState(null);
  const [stageMessage, setStageMessage] = useState("Waiting to start.");
  const [stageElapsed, setStageElapsed] = useState(0);

  useEffect(() => {
    fetch('http://localhost:5000/api/scenarios')
      .then(r => r.json())
      .then(data => setScenarios(data.scenarios || []))
      .catch(() => setProgress("Could not load scenarios. Check that the agent server is running."));
  }, []);

  useEffect(() => {
    if (!taskId) return undefined;
    const interval = setInterval(() => {
      fetch(`http://localhost:5000/api/task/${taskId}`)
        .then(async r => {
          const data = await r.json();
          if (!r.ok) throw new Error(data.error || "Fallback run failed.");
          return data;
        })
        .then(data => {
          setCurrentStage(data.stage || 0);
          setTrace(data.trace || []);
          setStageMessage(data.message || "Fallback is working locally.");
          setStageElapsed(data.elapsed_seconds || 0);
          if (data.status === "completed") {
            setResult(data.result);
            setProgress(null);
            setTaskId(null);
          } else if (data.status === "error") {
            setProgress("Error: " + data.error);
            setTaskId(null);
          }
        })
        .catch(error => {
          setProgress("Error: " + error.message);
          setTaskId(null);
        });
    }, 500);
    return () => clearInterval(interval);
  }, [taskId]);

  const runScenario = () => {
    if (!selected || taskId) return;
    setProgress("Starting local fallback...");
    setResult(null);
    setTrace([]);
    setCurrentStage(1);
    setStageMessage("Fallback mode only — no model/API calls.");
    setStageElapsed(0);

    fetch('http://localhost:5000/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario: selected })
    })
    .then(async r => {
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "Could not start fallback.");
      return data;
    })
    .then(data => {
      setTaskId(data.task_id);
      setProgress("Local fallback running — no API call.");
      setStageMessage(data.message || "Reading scenario data locally.");
    })
    .catch(error => setProgress("Error: " + error.message));
  };

  const stageConfig = [
    { key: 'perceive', label: 'Perceive', color: '#1976d2', icon: '👁️' },
    { key: 'reason', label: 'Reason', color: '#388e3c', icon: '🧠' },
    { key: 'act', label: 'Act', color: '#f57c00', icon: '⚡' },
    { key: 'observe', label: 'Evaluate', color: '#7b1fa2', icon: '🔍' }
  ];

  const renderStageData = turnData => {
    if (!turnData) return null;
    const output = turnData.output || turnData.decision || turnData.action || turnData;
    return (
      <div style={{ marginTop: "8px" }}>
        {turnData.input && (
          <details style={{ marginBottom: "8px" }}>
            <summary style={{ cursor: "pointer", color: "#555", fontSize: "12px" }}>Input passed into this stage</summary>
            <pre style={{ fontSize: "11px", background: "#f8f9fa", padding: "8px", borderRadius: "4px", overflow: "auto", maxHeight: "180px", whiteSpace: "pre-wrap" }}>
              {JSON.stringify(turnData.input, null, 2)}
            </pre>
          </details>
        )}
        {turnData.prompt && (
          <details style={{ marginBottom: "8px" }}>
            <summary style={{ cursor: "pointer", color: "#1976d2", fontSize: "12px", fontWeight: "bold" }}>Prompt sent to model</summary>
            <pre style={{ fontSize: "11px", background: "#e3f2fd", padding: "8px", borderRadius: "4px", overflow: "auto", maxHeight: "220px", whiteSpace: "pre-wrap" }}>
              {turnData.prompt}
            </pre>
          </details>
        )}
        <strong style={{ fontSize: "12px" }}>Stage output</strong>
        <pre style={{ fontSize: "11px", background: "#fff", padding: "8px", borderRadius: "4px", overflow: "auto", maxHeight: "220px", whiteSpace: "pre-wrap" }}>
          {JSON.stringify(output, null, 2)}
        </pre>
        <small style={{ color: "#777" }}>Source: {turnData.source || "fallback_simulation"}</small>
      </div>
    );
  };

  return (
    <div style={{ maxWidth: "1000px", margin: "0 auto", padding: "20px", fontFamily: "sans-serif" }}>
      <h1 style={{ color: "#1565c0", borderBottom: "2px solid #1565c0", paddingBottom: "10px" }}>🏦 Bank Agent Dashboard</h1>
      <div style={{ display: "flex", gap: "15px", flexWrap: "wrap", margin: "15px 0" }}>
        <select value={selected} onChange={e => setSelected(e.target.value)} style={{ padding: "10px", fontSize: "16px", borderRadius: "4px", border: "1px solid #ccc" }}>
          <option value="">-- Select Scenario --</option>
          {scenarios.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <button onClick={runScenario} disabled={!selected || Boolean(taskId)} style={{ padding: "10px 20px", fontSize: "16px", cursor: "pointer", background: "#1976d2", color: "white", border: "none", borderRadius: "4px", fontWeight: "bold", opacity: !selected || taskId ? 0.6 : 1 }}>▶ Run Local Fallback</button>
      </div>

      {progress && <div style={{ padding: "12px", background: "#fff3e0", border: "1px solid #ff9800", borderRadius: "8px", margin: "10px 0" }}>⏳ {progress}</div>}

      {(taskId || trace.length > 0 || result) && (
        <div style={{ marginTop: "20px" }}>
          <h3 style={{ color: "#1565c0", marginBottom: "6px" }}>Local Fallback Trace</h3>
          <div style={{ color: "#555", fontSize: "13px", marginBottom: "10px" }}>No model/API calls. Each stage shows its input and output.</div>
          <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", marginBottom: "15px" }}>
            {stageConfig.map((stage, i) => {
              const turnData = trace.find(t => t.stage === stage.key) || null;
              const isComplete = Boolean(turnData);
              const isActive = !isComplete && taskId && currentStage === i + 1;
              return (
                <div key={stage.key} style={{ flex: "1 1 220px", minWidth: "220px", padding: "15px", borderRadius: "8px", border: `2px solid ${isComplete || isActive ? stage.color : "#ccc"}`, background: isActive ? "#fff8e1" : isComplete ? "#fff" : "#f5f5f5", opacity: isComplete || isActive ? 1 : 0.6, transition: "all 0.3s ease" }}>
                  <div style={{ fontSize: "20px", marginBottom: "8px" }}>{stage.icon}</div>
                  <div style={{ color: stage.color, fontWeight: "bold" }}>{stage.label} {isActive ? "— in progress" : isComplete ? "— complete" : "— waiting"}</div>
                  {isActive && <div style={{ marginTop: "8px", color: "#555", fontSize: "12px" }}>{stageMessage}<br /><strong>{stageElapsed}s elapsed</strong></div>}
                  {renderStageData(turnData)}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {result && (
        <div style={{ marginTop: "15px", padding: "12px", background: "#e8f5e9", borderRadius: "8px", border: "2px solid #4caf50" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
            <strong style={{ fontSize: "18px" }}>Final Decision:</strong>
            <span style={{ fontSize: "20px", fontWeight: "bold", color: "#4caf50" }}>{result.score}/{result.max_score} ({Math.round(result.normalized * 100)}%)</span>
          </div>
          {result.scenario_input && (
            <details style={{ marginBottom: "12px", background: "#f1f8e9", padding: "8px", borderRadius: "4px" }}>
              <summary style={{ cursor: "pointer", fontWeight: "bold", fontSize: "13px", color: "#33691e" }}>Scenario Input (trigger, financials, regulations)</summary>
              <pre style={{ fontSize: "11px", background: "#fff", padding: "8px", borderRadius: "4px", overflow: "auto", maxHeight: "240px", whiteSpace: "pre-wrap", marginTop: "8px" }}>
                {JSON.stringify(result.scenario_input, null, 2)}
              </pre>
            </details>
          )}
          <div style={{ fontSize: "14px" }}>
            <strong>News label:</strong> {result.final_action?.news_label || "N/A"}<br />
            <strong>Action:</strong> {result.final_action?.action || "N/A"}<br />
            <strong>Amount:</strong> {result.final_action?.amount || 0}<br />
            <strong>Confidence:</strong> {result.final_action?.confidence || 0}<br />
            <strong>Rationale:</strong><br /><em style={{ fontSize: "12px" }}>{result.final_action?.rationale || "N/A"}</em>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
