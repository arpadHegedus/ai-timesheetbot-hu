import React, { useEffect, useRef, useState } from 'react';
import SubmissionOverlay from './components/SubmissionOverlay';

const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;
const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;

// UK date format (DD/MM/YYYY), matching the PDF timesheet this table previews.
const ukDate = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-GB');
};
const huDateTime = (iso) => new Date(iso).toLocaleString('hu-HU', { dateStyle: 'medium', timeStyle: 'short' });
const fmtHours = (v) => (v ? String(v) : ''); // blank for zero, matching the PDF's per-day cells

async function api(path, token, body, { blob = false, method } = {}) {
  const res = await fetch(`/api${path}`, {
    method: method || (body === undefined ? 'GET' : 'POST'),
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))).detail;
    const err = new Error(typeof detail === 'string' ? detail : `Szerverhiba (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return blob ? res.blob() : res.json();
}

// --- Icons (inline so they inherit currentColor and need no asset pipeline) ---
const IconMenu = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" {...p}>
    <path d="M4 6h16M4 12h16M4 18h16" />
  </svg>
);
const IconClose = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" {...p}>
    <path d="M6 6l12 12M18 6L6 18" />
  </svg>
);
const IconMic = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" {...p}>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
  </svg>
);
const IconArrowUp = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M12 19V5M5 12l7-7 7 7" />
  </svg>
);
const IconTrash = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0-.8 12.1a2 2 0 0 1-2 1.9H9.8a2 2 0 0 1-2-1.9L7 7h10Z" />
  </svg>
);
const IconRestart = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M4 4v5h5M20 20v-5h-5" />
    <path d="M4.6 15a8 8 0 1 0 1.7-8.7L4 9M20 15l-1.7 2.7" />
  </svg>
);

export default function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem('token') || '');
  const [email, setEmail] = useState(() => sessionStorage.getItem('email') || '');
  const authed = !!token;
  const signInBtn = useRef(null);
  const [authError, setAuthError] = useState('');
  const [messages, setMessages] = useState([]);
  const [entries, setEntries] = useState([]); // raw AI entries, kept only to resend on submit
  const [rows, setRows] = useState([]); // grouped per-day rows for the preview table
  const [totals, setTotals] = useState(null);
  const [ready, setReady] = useState(false);
  const [history, setHistory] = useState([]);
  const [historyError, setHistoryError] = useState('');
  const [deletingId, setDeletingId] = useState(null);
  const [drawer, setDrawer] = useState(false);
  const [input, setInput] = useState('');
  const [thinking, setThinking] = useState(false);
  const [listening, setListening] = useState(false);
  const [overlay, setOverlay] = useState('idle');
  const [error, setError] = useState(null);
  const [online, setOnline] = useState(navigator.onLine);
  const feedEnd = useRef(null);
  const textareaRef = useRef(null);
  const MAX_INPUT_LINES = 5;

  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener('online', on);
    window.addEventListener('offline', off);
    return () => {
      window.removeEventListener('online', on);
      window.removeEventListener('offline', off);
    };
  }, []);

  useEffect(() => {
    feedEnd.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, thinking, ready]);

  // Grow the composer with its content, up to MAX_INPUT_LINES, then scroll internally.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    const lineHeight = parseFloat(getComputedStyle(el).lineHeight) || 20;
    const maxHeight = lineHeight * MAX_INPUT_LINES;
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
    el.style.overflowY = el.scrollHeight > maxHeight ? 'auto' : 'hidden';
  }, [input]);

  const logout = (msg = '') => {
    sessionStorage.removeItem('token');
    sessionStorage.removeItem('email');
    window.google?.accounts.id.disableAutoSelect();
    setToken('');
    setEmail('');
    setMessages([]);
    setEntries([]);
    setRows([]);
    setTotals(null);
    setReady(false);
    setHistory([]);
    setDrawer(false);
    setAuthError(msg);
  };

  const guard = (err) => {
    if (err.status === 401) return logout('A munkamenet lejárt. Jelentkezz be újra.');
    setError(err.message || 'Váratlan hiba történt.');
  };

  const loadHistory = async (tok = token) => {
    try {
      setHistory(await api('/history', tok));
      setHistoryError('');
    } catch (err) {
      if (err.status === 401) return guard(err);
      setHistoryError(err.message);
    }
  };

  useEffect(() => {
    if (authed) loadHistory();
  }, [authed]);

  const handleCredential = async ({ credential }) => {
    try {
      const data = await api('/auth/google', '', { credential });
      sessionStorage.setItem('token', data.token);
      sessionStorage.setItem('email', data.email);
      setToken(data.token);
      setEmail(data.email);
      setAuthError('');
    } catch (err) {
      setAuthError(err.message);
    }
  };

  useEffect(() => {
    if (authed) return;
    const t = setInterval(() => {
      if (!window.google || !signInBtn.current) return;
      clearInterval(t);
      window.google.accounts.id.initialize({ client_id: CLIENT_ID, callback: handleCredential });
      window.google.accounts.id.renderButton(signInBtn.current, {
        theme: 'filled_black', size: 'large', shape: 'pill', locale: 'hu',
      });
    }, 100);
    return () => clearInterval(t);
  }, [authed]);

  const send = async () => {
    const text = input.trim();
    if (!text || thinking) return;
    const next = [...messages, { role: 'user', text }];
    setMessages(next);
    setInput('');
    setThinking(true);
    setReady(false);
    setError(null);
    try {
      const data = await api('/chat', token, { messages: next });
      setMessages([...next, { role: 'assistant', text: data.reply }]);
      setEntries(data.entries);
      setRows(data.rows);
      setTotals(data.totals);
      setReady(data.ready);
    } catch (err) {
      guard(err);
    } finally {
      setThinking(false);
    }
  };

  const submit = async () => {
    setOverlay('loading');
    setError(null);
    try {
      const data = await api('/submit-report', token, { entries });
      if (!data.saved) setError('A jelentés elment e-mailben, de az előzmények közé nem sikerült menteni.');
      loadHistory();
      setOverlay('success');
    } catch (err) {
      setOverlay('idle');
      guard(err);
    }
  };

  const dismiss = () => {
    setMessages([]);
    setEntries([]);
    setRows([]);
    setTotals(null);
    setReady(false);
    setOverlay('idle');
  };

  const startOver = () => {
    setMessages([]);
    setEntries([]);
    setRows([]);
    setTotals(null);
    setReady(false);
    setInput('');
    setError(null);
  };

  const openPdf = async (id) => {
    const w = window.open('', '_blank'); // open synchronously to avoid popup blockers
    try {
      const blob = await api(`/reports/${id}/pdf`, token, undefined, { blob: true });
      const url = URL.createObjectURL(blob);
      if (w) w.location = url;
      else window.location = url;
    } catch (err) {
      w?.close();
      guard(err);
    }
  };

  const deleteReport = async (id, e) => {
    e.stopPropagation();
    if (!window.confirm('Biztosan törlöd ezt a jelentést?')) return;
    setDeletingId(id);
    const prev = history;
    setHistory((h) => h.filter((r) => r.id !== id)); // optimistic
    try {
      await api(`/reports/${id}`, token, undefined, { method: 'DELETE' });
    } catch (err) {
      setHistory(prev); // roll back
      guard(err);
    } finally {
      setDeletingId(null);
    }
  };

  const listen = () => {
    if (!SpeechRec) return setError('A hangbevitelt ez a böngésző nem támogatja.');
    const rec = new SpeechRec();
    rec.lang = 'hu-HU';
    rec.onstart = () => setListening(true);
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    rec.onresult = (ev) => setInput((prev) => `${prev} ${ev.results[0][0].transcript}`.trim());
    rec.start();
  };

  if (!authed) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-slate-900 p-4">
        <div className="w-full max-w-sm rounded-xl bg-slate-800 p-6 shadow-2xl space-y-4">
          <div className="text-center">
            <h1 className="text-2xl font-bold text-white">Munkaidő-nyilvántartó</h1>
            <p className="text-sm text-slate-400">Jelentkezz be a Google-fiókoddal</p>
          </div>
          {authError && (
            <div className="rounded-lg bg-red-500/10 border border-red-500/50 p-3 text-sm text-red-400">{authError}</div>
          )}
          <div ref={signInBtn} className="flex justify-center" />
        </div>
      </div>
    );
  }

  const canSend = !thinking && input.trim() && online;

  return (
    <div className="flex flex-col h-screen bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 overflow-hidden">
      <SubmissionOverlay status={overlay} onDismiss={dismiss} />

      {/* Fejléc */}
      <header className="flex items-center gap-3 bg-slate-900 dark:bg-black text-white px-4 h-14 shrink-0">
        <button onClick={() => setDrawer(true)} aria-label="Menü megnyitása" className="p-2 -ml-2 rounded-lg hover:bg-slate-800">
          <IconMenu className="w-6 h-6" />
        </button>
        <h1 className="text-lg font-semibold flex-1 truncate">Munkaidő</h1>
        {messages.length > 0 && (
          <button
            onClick={startOver}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs text-slate-300 border border-slate-700 hover:bg-slate-800 hover:text-white transition-colors"
          >
            <IconRestart className="w-3.5 h-3.5" />
            Újrakezdés
          </button>
        )}
      </header>

      {/* Oldalsáv (fiók + előzmények) */}
      {drawer && <div className="fixed inset-0 z-40 bg-black/50" onClick={() => setDrawer(false)} />}
      <aside
        className={`fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] bg-slate-900 dark:bg-black text-white p-4 flex flex-col justify-between transition-transform duration-200 ${
          drawer ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="min-h-0 flex flex-col">
          <div className="flex items-center justify-between mb-4 border-b border-slate-700 pb-2">
            <h2 className="text-lg font-bold">Előzmények</h2>
            <button onClick={() => setDrawer(false)} aria-label="Bezárás" className="text-slate-400 hover:text-white">
              <IconClose className="w-5 h-5" />
            </button>
          </div>
          <ul className="space-y-2 overflow-y-auto">
            {historyError && <li className="text-xs text-red-400">{historyError}</li>}
            {!historyError && history.length === 0 && (
              <li className="text-xs text-slate-500 italic">Még nincs elküldött jelentés.</li>
            )}
            {history.map((h) => (
              <li key={h.id} className="group flex items-stretch gap-1">
                <button onClick={() => openPdf(h.id)} className="flex-1 min-w-0 text-left px-3 py-2 bg-slate-800 rounded-md hover:bg-slate-700">
                  <div className="text-sm font-medium">{h.period} · {h.total} óra</div>
                  <div className="text-xs text-slate-400">{huDateTime(h.created_at)} · PDF megnyitása</div>
                </button>
                <button
                  onClick={(e) => deleteReport(h.id, e)}
                  disabled={deletingId === h.id}
                  aria-label="Jelentés törlése"
                  className="px-2 rounded-md text-slate-500 hover:text-red-400 hover:bg-slate-800 disabled:opacity-40"
                >
                  <IconTrash className="w-4 h-4" />
                </button>
              </li>
            ))}
          </ul>
        </div>
        <button onClick={() => logout()} className="text-left text-xs text-slate-400 hover:text-white pt-4 border-t border-slate-800 truncate">
          {email} · Kijelentkezés
        </button>
      </aside>

      <main className="flex-1 flex flex-col p-4 min-w-0 min-h-0">
        {!online && (
          <div className="bg-amber-600 text-white px-4 py-2 rounded-lg text-sm mb-2">⚠ Nincs internetkapcsolat. A küldés le van tiltva.</div>
        )}
        {error && (
          <div className="bg-red-600 text-white p-3 rounded-lg text-sm mb-2 flex justify-between">
            <span>{error}</span>
            <button onClick={() => setError(null)}>✕</button>
          </div>
        )}

        <div className="flex-1 overflow-y-auto space-y-3 p-2">
          {messages.length === 0 && (
            <div className="flex h-full items-center justify-center text-center text-slate-400 dark:text-slate-500 text-sm">
              Írd le, hol dolgoztál, például: „Szeptember 28-án 6 órát dolgoztam a Moreland Avenue-n, 29-én 4 órát az Ady Wattsban."
            </div>
          )}
          {messages.map((m, i) => (
            <div
              key={i}
              className={`p-3 rounded-lg max-w-xl text-sm ${
                m.role === 'user'
                  ? 'bg-indigo-600 text-white ml-auto'
                  : 'bg-slate-200 text-slate-800 dark:bg-slate-800 dark:text-slate-100'
              }`}
            >
              {m.text}
            </div>
          ))}
          {thinking && <div className="text-slate-400 dark:text-slate-500 text-sm">Gondolkodom…</div>}

          {rows.length > 0 && !thinking && (
            <div className="border border-slate-200 dark:border-slate-800 rounded-lg bg-white dark:bg-slate-900 text-sm max-w-xl overflow-hidden">
              <div className="px-3 py-2 bg-slate-100 dark:bg-slate-800 font-medium">Summary</div>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="text-left text-xs text-slate-500 dark:text-slate-400">
                      <th className="px-3 py-1.5 font-normal">Day</th>
                      <th className="px-3 py-1.5 font-normal">Date</th>
                      <th className="px-3 py-1.5 font-normal text-right">Regular</th>
                      <th className="px-3 py-1.5 font-normal text-right">Overtime</th>
                      <th className="px-3 py-1.5 font-normal text-right">Sick</th>
                      <th className="px-3 py-1.5 font-normal text-right">Holiday</th>
                      <th className="px-3 py-1.5 font-normal">Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr key={i} className="border-t border-slate-100 dark:border-slate-800">
                        <td className="px-3 py-1.5 whitespace-nowrap">{r.weekday}</td>
                        <td className="px-3 py-1.5 whitespace-nowrap">{ukDate(r.date)}</td>
                        <td className="px-3 py-1.5 text-right">{fmtHours(r.regular)}</td>
                        <td className="px-3 py-1.5 text-right">{fmtHours(r.overtime)}</td>
                        <td className="px-3 py-1.5 text-right">{fmtHours(r.sick)}</td>
                        <td className="px-3 py-1.5 text-right">{fmtHours(r.holiday)}</td>
                        <td className="px-3 py-1.5 text-slate-500 dark:text-slate-400">{r.notes}</td>
                      </tr>
                    ))}
                    {totals && (
                      <tr className="border-t border-slate-100 dark:border-slate-800 font-semibold bg-slate-50 dark:bg-slate-800/60">
                        <td className="px-3 py-1.5" colSpan={2}>Total</td>
                        <td className="px-3 py-1.5 text-right">{totals.regular}</td>
                        <td className="px-3 py-1.5 text-right">{totals.overtime}</td>
                        <td className="px-3 py-1.5 text-right">{totals.sick}</td>
                        <td className="px-3 py-1.5 text-right">{totals.holiday}</td>
                        <td />
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              {ready && (
                <div className="p-3 border-t border-slate-100 dark:border-slate-800">
                  <button
                    onClick={submit}
                    disabled={overlay === 'loading' || !online}
                    className="w-full bg-emerald-600 hover:bg-emerald-700 text-white py-2.5 rounded-lg font-medium disabled:opacity-40"
                  >
                    Jelentés elküldése
                  </button>
                </div>
              )}
            </div>
          )}
          <div ref={feedEnd} />
        </div>

        {/* Egyesített csevegőmező: mikrofon + szöveg + küldés egy kapszulában (Gemini-stílus) */}
        <div className="pt-2">
          <div className="flex items-end gap-1 rounded-3xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 pl-2 pr-1.5 py-1.5 focus-within:border-indigo-500 transition-colors">
            <button
              onClick={listen}
              disabled={!online}
              title="Hangbevitel"
              aria-label="Hangbevitel"
              className={`shrink-0 p-2 rounded-full transition-colors disabled:opacity-40 ${
                listening
                  ? 'bg-red-100 text-red-600 dark:bg-red-500/20 dark:text-red-400'
                  : 'text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800'
              }`}
            >
              <IconMic className="w-5 h-5" />
            </button>
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              disabled={thinking || !online}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault(); // Enter sends; Shift+Enter adds a line
                  send();
                }
              }}
              placeholder={online ? 'Írd be a munkaóráidat...' : 'Nincs kapcsolat...'}
              className="flex-1 min-w-0 bg-transparent px-2 py-1.5 outline-none resize-none leading-5 disabled:opacity-60 placeholder:text-slate-400 dark:placeholder:text-slate-500"
            />
            <button
              onClick={send}
              disabled={!canSend}
              aria-label="Küldés"
              className="shrink-0 p-2 rounded-full bg-slate-900 dark:bg-indigo-600 text-white disabled:bg-slate-200 disabled:text-slate-400 dark:disabled:bg-slate-800 dark:disabled:text-slate-600 transition-colors"
            >
              <IconArrowUp className="w-5 h-5" />
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
