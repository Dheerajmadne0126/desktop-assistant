import { useState, useEffect, useRef } from 'react';
import './index.css';

export default function App() {
  const [state, setState] = useState('IDLE');
  const [statusMessage, setStatusMessage] = useState('Initializing system...');
  const [history, setHistory] = useState([]);

  const wsRef = useRef(null);
  const logEndRef = useRef(null);

  useEffect(() => {
    if (logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [history]);

  useEffect(() => {
    let disposed = false;
    let intentionalClose = false;
    let reconnectTimer = null;

    const connectWs = () => {
      if (disposed) return;
      const wsUrl = `ws://${window.location.hostname}:8000/ws/events`;
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        if (disposed) { ws.close(); return; }
        setStatusMessage('System Online. Listening for wake word...');
      };

      ws.onmessage = (event) => {
        if (disposed) return;
        try {
          const data = JSON.parse(event.data);

          if (data.type === 'state_change') {
            setState(data.state);
            if (data.message) setStatusMessage(data.message);
          } else if (data.type === 'transcription') {
            setHistory(prev => {
              const last = prev[prev.length - 1];
              if (last && last.text === data.text) return prev;
              return [...prev, { time: new Date().toLocaleTimeString(), text: data.text }];
            });
          }
        } catch (e) {
          console.error("WS Parse error", e);
        }
      };

      ws.onclose = () => {
        if (disposed || intentionalClose) return;
        setStatusMessage('Connection lost. Reconnecting...');
        setState('ERROR');
        reconnectTimer = setTimeout(connectWs, 3000);
      };

      wsRef.current = ws;
    };

    connectWs();

    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      const ws = wsRef.current;
      if (ws) {
        intentionalClose = true;
        ws.onclose = null;
        ws.close();
      }
      wsRef.current = null;
    };
  }, []);

  const handleManualTrigger = async () => {
    setStatusMessage('Triggering listen...');
    try {
      const res = await fetch(`http://${window.location.hostname}:8000/voice/listen`, { method: 'POST' });
      const data = await res.json();
      setStatusMessage(data.started ? 'Listening... speak now.' : data.detail);
    } catch (e) {
      setStatusMessage('Backend not reachable.');
    }
  };

  const getDisplayState = () => {
    if (state === 'LISTENING_FOR_WAKE_WORD' || state === 'IDLE') return 'JARVIS';
    if (state === 'LISTENING_FOR_COMMAND') return 'LISTENING';
    if (state === 'THINKING') return 'THINKING...';
    if (state === 'EXECUTING') return 'EXECUTING...';
    if (state === 'SPEAKING') return 'RESPONDING...';
    if (state === 'ERROR') return 'ERROR';
    return state;
  };

  return (
    <div className="w-screen h-screen flex flex-col bg-[#050a14] text-[#00e5ff] font-mono overflow-hidden relative">
      <div className="crt-overlay"></div>

      {/* Header */}
      <header className="flex justify-between items-center p-6 border-b border-[#00e5ff]/30 relative z-10">
        <div className="flex flex-col">
          <h1 className="text-3xl font-bold glow-text tracking-widest">JARVIS OS</h1>
          <span className="text-xs text-[#00e5ff]/70">v4.0_REBUILD</span>
        </div>
        <div className="flex gap-8 text-sm">
          <div className="flex flex-col items-end">
            <span className="text-[#00e5ff]/50">MIC STATUS</span>
            <span className={state !== 'ERROR' ? "text-[#00e5ff]" : "text-red-500"}>
              {state !== 'ERROR' ? 'ACTIVE' : 'OFFLINE'}
            </span>
          </div>
          <div className="flex flex-col items-end">
            <span className="text-[#00e5ff]/50">AI CORE</span>
            <span className={state !== 'ERROR' ? "text-[#00e5ff]" : "text-red-500"}>
              {state !== 'ERROR' ? 'ONLINE' : 'OFFLINE'}
            </span>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 flex relative z-10 overflow-hidden min-h-0">

        {/* Left Panel: Command History */}
        <div className="w-1/4 border-r border-[#00e5ff]/30 p-6 flex flex-col h-full min-h-0">
          <h2 className="text-xl mb-4 border-b border-[#00e5ff]/30 pb-2">TERMINAL LOG</h2>
          <div className="flex-1 overflow-y-auto pr-2 space-y-4">
            {history.length === 0 ? (
              <div className="text-[#00e5ff]/40 text-sm italic">Awaiting inputs...</div>
            ) : (
              history.map((log, i) => (
                <div key={i} className="text-sm">
                  <div className="text-xs text-[#00e5ff]/50">[{log.time}]</div>
                  <div className={log.text.startsWith('JARVIS:') ? 'text-[#00e5ff]' : 'text-white'}>
                    {log.text}
                  </div>
                </div>
              ))
            )}
            <div ref={logEndRef} />
          </div>
        </div>

        {/* Center Panel: AI Core Visualizer */}
        <div className="flex-1 flex flex-col items-center justify-center p-6">
          <div className="mb-12 text-center h-20">
            <h2 className="text-4xl font-bold tracking-widest glow-text">{getDisplayState()}</h2>
            <p className="mt-2 text-[#00e5ff]/70">{statusMessage}</p>
          </div>

          <div className="relative flex items-center justify-center w-full h-80">
            <div className={`hud-container ${state.toLowerCase()}`}>
              <div className="hud-ring hud-outer"></div>
              <div className="hud-ring hud-middle"></div>
              <div className="hud-ring hud-inner"></div>
              <div className="hud-core">
                <span className="hud-text">J.A.R.V.I.S</span>
              </div>
            </div>
          </div>

          <button
            onClick={handleManualTrigger}
            className="mt-8 px-8 py-3 border border-[#00e5ff] text-[#00e5ff] hover:bg-[#00e5ff]/20 active:bg-[#00e5ff]/40 rounded transition-colors text-sm uppercase tracking-widest"
          >
            ● Manual Listen
          </button>
        </div>

        {/* Right Panel: System */}
        <div className="w-1/4 p-6 flex flex-col h-full min-h-0 bg-[#02050a] border-l border-[#00e5ff]/30">
          <h2 className="text-xl mb-4 border-b border-[#00e5ff]/30 pb-2">SYSTEM</h2>
          <div className="border border-[#00e5ff]/20 p-3 bg-[#050a14]">
            <div className="flex justify-between items-center mb-2">
              <span className="font-bold text-sm">Laptop / PC</span>
              <span className={`text-xs ${state !== 'ERROR' ? 'text-[#00e5ff]' : 'text-red-500'}`}>
                ● {state !== 'ERROR' ? 'ONLINE' : 'OFFLINE'}
              </span>
            </div>
            <div className="text-xs text-[#00e5ff]/50">Core AI System</div>
          </div>
        </div>
      </main>
    </div>
  );
}
