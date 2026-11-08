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
          if (!r.ok) throw new Error(data.error || "LLM run failed.");
          return data;
        })
        .then(data => {
          setCurrentStage(data.stage || 0);
          setTrace(data.trace || []);
          setStageMessage(data.message || "Waiting for the LLM response.");
          setStageElapsed(data.elapsed_seconds || 0);
          if (data.status === "completed") {
            setResult(data.result);
            setProgress(null);
            setTaskId(null);
          } else if (data.status === "error") {
            setResult(data.result);
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
    setProgress("Starting LLM agents...");
    setResult(null);
    setTrace([]);
    setCurrentStage(1);
    setStageMessage("Calling the agents through Hermes.");
    setStageElapsed(0);

    fetch('http://localhost:5000/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario: selected })
    })
    .then(async r => {
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "Could not start LLM agents.");
      return data;
    })
    .then(data => {
      setTaskId(data.task_id);
      setProgress("LLM agents running...");
      setStageMessage(data.message || "Main agent is assessing the scenario.");
    })
    .catch(error => setProgress("Error: " + error.message));
  };

  const stageConfig = [
    { key: 'baseline', label: 'Baseline LLM', color: '#1976d2', icon: '1' },
    { key: 'secondary', label: 'Secondary agents', color: '#388e3c', icon: '2' },
    { key: 'observe', label: 'Evaluate baseline', color: '#7b1fa2', icon: '3' }
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
        <small style={{ color: "#777" }}>Source: {turnData.source || "unknown"}{turnData.model ? ` | Model: ${turnData.model}` : ""}</small>
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
        <button onClick={runScenario} disabled={!selected || Boolean(taskId)} style={{ padding: "10px 20px", fontSize: "16px", cursor: "pointer", background: "#1976d2", color: "white", border: "none", borderRadius: "4px", fontWeight: "bold", opacity: !selected || taskId ? 0.6 : 1 }}>▶ Run LLM Agents</button>
      </div>

      {progress && <div style={{ padding: "12px", background: "#fff3e0", border: "1px solid #ff9800", borderRadius: "8px", margin: "10px 0" }}>⏳ {progress}</div>}

      {(taskId || trace.length > 0 || result) && (
        <div style={{ marginTop: "20px" }}>
          <h3 style={{ color: "#1565c0", marginBottom: "6px" }}>LLM Agent Trace</h3>
          <div style={{ color: "#555", fontSize: "13px", marginBottom: "10px" }}>Two independent lines receive the same scenario: baseline LLM and secondary specialist agents.</div>
          <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", marginBottom: "15px" }}>
            {stageConfig.map((stage, i) => {
              const stageEntries = trace.filter(t => t.stage === stage.key);
              const turnData = stageEntries[0] || null;
              const isComplete = Boolean(turnData);
              const isActive = !isComplete && taskId && currentStage === i + 1;
              return (
                <div key={stage.key} style={{ flex: "1 1 220px", minWidth: "220px", padding: "15px", borderRadius: "8px", border: `2px solid ${isComplete || isActive ? stage.color : "#ccc"}`, background: isActive ? "#fff8e1" : isComplete ? "#fff" : "#f5f5f5", opacity: isComplete || isActive ? 1 : 0.6, transition: "all 0.3s ease" }}>
                  <div style={{ fontSize: "20px", marginBottom: "8px" }}>{stage.icon}</div>
                  <div style={{ color: stage.color, fontWeight: "bold" }}>{stage.label} {isActive ? "— in progress" : isComplete ? "— complete" : "— waiting"}</div>
                  {isActive && <div style={{ marginTop: "8px", color: "#555", fontSize: "12px" }}>{stageMessage}<br /><strong>{stageElapsed}s elapsed</strong></div>}
                  {stageEntries.map((entry, index) => <div key={index}>{renderStageData(entry)}</div>)}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {result && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "16px", marginTop: "15px" }}>
          <section style={{ flex: "1 1 360px", padding: "16px", border: "2px solid #1976d2", borderRadius: "8px" }}>
            <h2>Baseline LLM</h2>
            <p>Main agent decision from the scenario alone.</p>
            {result.baseline?.status === "error" ? <p role="alert">{result.baseline.error}</p> : (
              <>
                <strong>Score: {result.baseline?.score}/{result.baseline?.max_score} ({Math.round((result.baseline?.normalized || 0) * 100)}%)</strong>
                <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(result.baseline?.decision, null, 2)}</pre>
              </>
            )}
          </section>
          <section style={{ flex: "1 1 360px", padding: "16px", border: "2px solid #388e3c", borderRadius: "8px" }}>
            <h2>Secondary agent line</h2>
            <p>{result.secondary?.note}</p>
            {Object.entries(result.secondary?.agents || {}).map(([name, agent]) => (
              <div key={name}>
                <h3>{name.replace(/_/g, ' ')}</h3>
                {agent.status === "error" ? <p role="alert">{agent.error}</p> : (
                  <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(agent.output, null, 2)}</pre>
                )}
              </div>
            ))}
          </section>
        </div>
      )}
    </div>
  );
}

export default App;
