import { useState, useEffect, useRef, type CSSProperties } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';

// Use environment variable for production, fallback to local dev server
const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

type UIInputConfig = {
  id: string;
  label: string;
  type: 'text' | 'select';
  placeholder?: string;
  options?: { label: string; value: string }[];
};

type Prototype = {
  id: string;
  name: string;
  description: string;
  ui: {
    title: string;
    subtitle: string;
    placeholder: string;
    readonly: boolean;
    mode?: 'chat' | 'voice_assessment';
    inputs: UIInputConfig[];
  }
};

type Message = {
  id: string;
  role: 'system' | 'user' | 'assistant';
  content: string;
};

type ChatSession = {
  id: string;
  prototype_id: string;
  user_id: string;
  messages: Message[];
};

type AssessmentData = {
  score: number;
  engagement_score: number;
  summary: string;
  tip?: string;
};

type VoiceStatus = 'idle' | 'connecting' | 'listening' | 'speaking' | 'connected' | 'error';

type VoiceMeter = {
  analyser: AnalyserNode;
  data: Uint8Array<ArrayBuffer>;
  source: MediaStreamAudioSourceNode;
};

const getErrorMessage = (error: unknown) => error instanceof Error ? error.message : 'An unexpected error occurred';

function App() {
  const [prototypes, setPrototypes] = useState<Prototype[]>([]);
  const [selectedPrototypeId, setSelectedPrototypeId] = useState<string>('');

  // inputValues stores the dynamic form inputs keyed by input id
  const [inputValues, setInputValues] = useState<Record<string, string>>({});

  // The state machine for our 3 pages
  const [view, setView] = useState<'landing' | 'splash' | 'chat'>('landing');

  const [session, setSession] = useState<ChatSession | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [inputValue, setInputValue] = useState('');

  // Ref for auto-scrolling
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // State for the assessment prototype specific UI
  const [assessmentData, setAssessmentData] = useState<AssessmentData | null>(null);
  const [savingScore, setSavingScore] = useState(false);

  const peerConnectionRef = useRef<RTCPeerConnection | null>(null);
  const dataChannelRef = useRef<RTCDataChannel | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null);
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus>('idle');
  const voiceStatusRef = useRef<VoiceStatus>('idle');
  const [voiceActive, setVoiceActive] = useState(false);
  const [voiceLevel, setVoiceLevel] = useState(0);
  const voiceLevelRef = useRef(0);
  const [voiceLog, setVoiceLog] = useState<string[]>([]);
  const audioContextRef = useRef<AudioContext | null>(null);
  const voiceMeterFrameRef = useRef<number | null>(null);
  const localVoiceMeterRef = useRef<VoiceMeter | null>(null);
  const remoteVoiceMeterRef = useRef<VoiceMeter | null>(null);

  const composerWrapRef = useRef<HTMLDivElement>(null);
  const [composerHeight, setComposerHeight] = useState(120);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    if (view === 'chat') {
      scrollToBottom();
    }
  }, [session?.messages, loading, view]);

  useEffect(() => {
    voiceStatusRef.current = voiceStatus;
  }, [voiceStatus]);

  useEffect(() => {
    if (view === 'chat' && composerWrapRef.current) {
      const resizeObserver = new ResizeObserver((entries) => {
        for (const entry of entries) {
          if (entry.target === composerWrapRef.current) {
             setComposerHeight(entry.contentRect.height);
             scrollToBottom(); // Re-scroll if height changes to maintain visibility
          }
        }
      });
      resizeObserver.observe(composerWrapRef.current);
      return () => resizeObserver.disconnect();
    }
  }, [view, assessmentData]); // Dependency on assessmentData to ensure ref is checked when UI changes

  useEffect(() => {
    fetch(`${API_BASE}/prototypes`)
      .then(r => r.json())
      .then(data => {
        setPrototypes(data);

        // Check URL for prototype query param (e.g. ?prototype=profile_builder)
        const params = new URLSearchParams(window.location.search);
        const urlPrototype = params.get('prototype');

        if (urlPrototype && data.find((p: Prototype) => p.id === urlPrototype)) {
          setSelectedPrototypeId(urlPrototype);
          setView('splash');
        } else if (data.length > 0) {
          setSelectedPrototypeId(data[0].id);
          setView('landing');
        }
      })
      .catch(() => setError('Failed to load prototypes. Ensure backend is running.'));
  }, []);

  const handleOpenSplash = () => {
    // Navigate via query param so the user has a shareable link
    const newUrl = new URL(window.location.href);
    newUrl.searchParams.set('prototype', selectedPrototypeId);
    window.history.pushState({}, '', newUrl);

    setError('');
    setView('splash');
  };

  const ensureAudioContext = () => {
    if (!audioContextRef.current) {
      audioContextRef.current = new AudioContext();
    }
    return audioContextRef.current;
  };

  const createVoiceMeter = (stream: MediaStream) => {
    const audioContext = ensureAudioContext();
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 256;
    analyser.smoothingTimeConstant = 0.74;

    const source = audioContext.createMediaStreamSource(stream);
    source.connect(analyser);

    return {
      analyser,
      data: new Uint8Array(new ArrayBuffer(analyser.frequencyBinCount)),
      source
    };
  };

  const startVoiceMeterLoop = () => {
    if (voiceMeterFrameRef.current !== null) return;

    const readMeterLevel = (meter: VoiceMeter | null) => {
      if (!meter) return 0;

      meter.analyser.getByteTimeDomainData(meter.data);
      const sumSquares = meter.data.reduce((sum, value) => {
        const centeredValue = (value - 128) / 128;
        return sum + centeredValue * centeredValue;
      }, 0);
      const rms = Math.sqrt(sumSquares / meter.data.length);
      return Math.min(1, rms * 4.6);
    };

    const tick = () => {
      const status = voiceStatusRef.current;
      const activeLevel = status === 'listening'
        ? readMeterLevel(localVoiceMeterRef.current)
        : status === 'speaking'
          ? readMeterLevel(remoteVoiceMeterRef.current)
          : 0;
      const easing = activeLevel > voiceLevelRef.current ? 0.42 : 0.16;
      const nextLevel = voiceLevelRef.current + (activeLevel - voiceLevelRef.current) * easing;

      voiceLevelRef.current = nextLevel;
      setVoiceLevel(nextLevel);
      voiceMeterFrameRef.current = window.requestAnimationFrame(tick);
    };

    voiceMeterFrameRef.current = window.requestAnimationFrame(tick);
  };

  const stopVoiceMeterLoop = () => {
    if (voiceMeterFrameRef.current !== null) {
      window.cancelAnimationFrame(voiceMeterFrameRef.current);
      voiceMeterFrameRef.current = null;
    }
  };

  const disconnectVoiceMeter = (meter: VoiceMeter | null) => {
    meter?.source.disconnect();
  };

  const resetVoiceConnection = () => {
    dataChannelRef.current?.close();
    peerConnectionRef.current?.close();
    localStreamRef.current?.getTracks().forEach(track => track.stop());
    stopVoiceMeterLoop();
    disconnectVoiceMeter(localVoiceMeterRef.current);
    disconnectVoiceMeter(remoteVoiceMeterRef.current);
    if (audioContextRef.current?.state !== 'closed') {
      void audioContextRef.current?.close();
    }
    dataChannelRef.current = null;
    peerConnectionRef.current = null;
    localStreamRef.current = null;
    remoteAudioRef.current = null;
    localVoiceMeterRef.current = null;
    remoteVoiceMeterRef.current = null;
    audioContextRef.current = null;
    voiceLevelRef.current = 0;
    setVoiceLevel(0);
    setVoiceActive(false);
    setVoiceStatus('idle');
  };

  useEffect(() => {
    return () => resetVoiceConnection();
    // Run only on unmount so active calls are not reset by render-time callback identity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleStartSession = async () => {
    // Validation: make sure all required fields defined in YAML have some value
    const prototype = prototypes.find(p => p.id === selectedPrototypeId);
    if (!prototype) return;

    for (const input of prototype.ui.inputs) {
      if (!inputValues[input.id]?.trim()) {
        setError(`Please enter a value for ${input.label}.`);
        return;
      }
    }

    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/chat/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prototype_id: selectedPrototypeId,
          inputs: inputValues
        })
      });
      if (!res.ok) throw new Error('Failed to start session');
      const data = await res.json();
      resetVoiceConnection();
      setAssessmentData(null);
      setVoiceLog([]);
      setSession(data);
      setView('chat');
    } catch (e: unknown) {
      setError(getErrorMessage(e));
    } finally {
      setLoading(false);
    }
  };

  const updateInputValue = (id: string, value: string) => {
    setInputValues(prev => ({ ...prev, [id]: value }));
  };

  const handleSend = async () => {
    if (!inputValue.trim() || !session || loading) return;

    const userContent = inputValue;
    setInputValue('');
    setLoading(true);

    // Optimistically update UI
    const tempId = `temp-${Date.now()}`;
    setSession({
      ...session,
      messages: [...session.messages, { id: tempId, role: 'user', content: userContent }]
    });

    try {
      const res = await fetch(`${API_BASE}/chat/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: session.id, content: userContent })
      });
      if (!res.ok) throw new Error('Failed to send message');

      const chatResponse = await res.json();

      // If this is the assessment prototype, the backend will return the score in structured_data
      if (chatResponse.structured_data && chatResponse.structured_data.score !== undefined) {
         // Calculate engagement score based on user messages word count
         const userMessages = session.messages.filter(m => m.role === 'user');
         const newUserMessages = [...userMessages, { id: tempId, role: 'user', content: userContent }];
         let totalWords = 0;
         for (const msg of newUserMessages) {
            // Very simple word count
            const words = msg.content.trim().split(/\s+/).filter(w => w.length > 0);
            totalWords += words.length;
         }
         const engagementScore = Math.min(100, totalWords);

         setAssessmentData({
           score: chatResponse.structured_data.score,
           engagement_score: engagementScore,
           summary: chatResponse.structured_data.summary || '',
           tip: chatResponse.structured_data.tip
         });
      }

      const sessionRes = await fetch(`${API_BASE}/chat/session/${session.id}`);
      const sessionData = await sessionRes.json();
      setSession(sessionData);
    } catch (e: unknown) {
      setError(getErrorMessage(e));
    } finally {
      setLoading(false);
    }
  };

  const activePrototype = prototypes.find(p => p.id === selectedPrototypeId);
  const activePrototypeUI = activePrototype?.ui;
  const isVoiceAssessment = activePrototypeUI?.mode === 'voice_assessment';


  const handleStartVoiceChat = async () => {
    if (!session || voiceStatus === 'connecting') return;

    resetVoiceConnection();
    setError('');
    setVoiceLog(['Connecting to the voice assessment...']);
    setVoiceStatus('connecting');

    try {
      const tokenRes = await fetch(`${API_BASE}/realtime/client-secret`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: session.id })
      });
      if (!tokenRes.ok) throw new Error('Failed to prepare voice session');
      const tokenData = await tokenRes.json();
      const ephemeralKey = tokenData.value || tokenData.client_secret?.value;
      if (!ephemeralKey) throw new Error('Voice session did not return an ephemeral key');

      const pc = new RTCPeerConnection();
      peerConnectionRef.current = pc;

      const audioElement = document.createElement('audio');
      audioElement.autoplay = true;
      remoteAudioRef.current = audioElement;
      pc.ontrack = (event) => {
        const [remoteStream] = event.streams;
        audioElement.srcObject = remoteStream;
        remoteVoiceMeterRef.current = createVoiceMeter(remoteStream);
        startVoiceMeterLoop();
      };

      const mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      localStreamRef.current = mediaStream;
      localVoiceMeterRef.current = createVoiceMeter(mediaStream);
      startVoiceMeterLoop();
      pc.addTrack(mediaStream.getTracks()[0]);

      const dc = pc.createDataChannel('oai-events');
      dataChannelRef.current = dc;

      dc.addEventListener('open', () => {
        setVoiceActive(true);
        setVoiceStatus('connected');
        setVoiceLog(prev => [...prev, 'Connected. The tutor will begin speaking shortly.']);
        dc.send(JSON.stringify({
          type: 'response.create',
          response: {
            instructions: 'Greet the student briefly and ask the first assessment question about the lesson objective.'
          }
        }));
      });

      dc.addEventListener('message', (event) => {
        const realtimeEvent = JSON.parse(event.data);

        if (realtimeEvent.type === 'input_audio_buffer.speech_started') {
          setVoiceStatus('listening');
        }
        if (realtimeEvent.type === 'response.audio.delta') {
          setVoiceStatus('speaking');
        }
        if (realtimeEvent.type === 'response.done') {
          setVoiceStatus('connected');
        }
        if (realtimeEvent.type === 'conversation.item.input_audio_transcription.completed' && realtimeEvent.transcript) {
          setVoiceLog(prev => [...prev.slice(-4), `You: ${realtimeEvent.transcript}`]);
        }
        if (realtimeEvent.type === 'response.audio_transcript.done' && realtimeEvent.transcript) {
          setVoiceLog(prev => [...prev.slice(-4), `Tutor: ${realtimeEvent.transcript}`]);
        }
        if (
          realtimeEvent.type === 'response.function_call_arguments.done' &&
          realtimeEvent.name === 'update_assessment_scores'
        ) {
          const args = JSON.parse(realtimeEvent.arguments || '{}');
          setAssessmentData({
            score: Math.max(0, Math.min(100, Number(args.understanding_score) || 0)),
            engagement_score: Math.max(0, Math.min(100, Number(args.engagement_score) || 0)),
            summary: args.summary || '',
            tip: args.tip
          });
        }
        if (realtimeEvent.type === 'error') {
          setVoiceStatus('error');
          setError(realtimeEvent.error?.message || 'Voice session error');
        }
      });

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      const sdpRes = await fetch('https://api.openai.com/v1/realtime/calls', {
        method: 'POST',
        body: offer.sdp,
        headers: {
          Authorization: `Bearer ${ephemeralKey}`,
          'Content-Type': 'application/sdp'
        }
      });
      if (!sdpRes.ok) throw new Error('Failed to connect voice chat');

      await pc.setRemoteDescription({
        type: 'answer',
        sdp: await sdpRes.text()
      });
    } catch (e: unknown) {
      resetVoiceConnection();
      setVoiceStatus('error');
      setError(getErrorMessage(e));
    }
  };

  const handleStopVoiceChat = () => {
    resetVoiceConnection();
    setVoiceLog(prev => [...prev, 'Voice chat ended.']);
  };

  const handleSaveScore = async () => {
    if (!session || !assessmentData || savingScore) return;
    setSavingScore(true);
    try {
      const res = await fetch(`${API_BASE}/chat/save-score`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: inputValues['user_id'] || 'unknown',
          lesson_topic: inputValues['lesson_code'] || 'unknown',
          score: assessmentData.score,
          engagement_score: assessmentData.engagement_score,
          summary: assessmentData.summary
        })
      });
      if (!res.ok) throw new Error('Failed to save score');
      alert('Score saved successfully!');
    } catch (e: unknown) {
      alert(`Error saving score: ${getErrorMessage(e)}`);
    } finally {
      setSavingScore(false);
    }
  };

  if (view === 'landing') {
    return (
      <div className="act-app-shell">
        <div className="act-app-header">
          <div className="act-brand">AI Prototype Starter</div>
        </div>
        <main className="act-main">
          <section className="act-welcome-card">
            <h1>Developer Landing Page</h1>
            <p>Select a prototype to open its user-facing splash screen.</p>

            <div className="act-form-row">
              <label>Prototype</label>
              <select
                value={selectedPrototypeId}
                onChange={e => setSelectedPrototypeId(e.target.value)}
              >
                {prototypes.map(p => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>

            <button
              className="act-primary-btn"
              onClick={handleOpenSplash}
              disabled={prototypes.length === 0}
            >
              Open
            </button>
          </section>
        </main>
      </div>
    );
  }

  if (view === 'splash' && activePrototypeUI) {
    return (
      <div className="act-app-shell">
        <div className="act-app-header">
          <div className="act-brand">{activePrototypeUI.title}</div>
        </div>
        <main className="act-main">
          <section className="act-welcome-card">
            <h1>Welcome</h1>
            <p>{activePrototypeUI.subtitle || 'Please fill out the information below to begin.'}</p>

            {activePrototypeUI.inputs.map(input => (
               <div key={input.id} className="act-form-row">
                 <label>{input.label}</label>
                 {input.type === 'select' && input.options ? (
                   <select
                     value={inputValues[input.id] || ''}
                     onChange={e => updateInputValue(input.id, e.target.value)}
                   >
                     <option value="" disabled>Select {input.label}</option>
                     {input.options.map(opt => (
                       <option key={opt.value} value={opt.value}>{opt.label}</option>
                     ))}
                   </select>
                 ) : (
                   <input
                     type="text"
                     placeholder={input.placeholder || ''}
                     value={inputValues[input.id] || ''}
                     onChange={e => updateInputValue(input.id, e.target.value)}
                   />
                 )}
               </div>
            ))}

            {error && <div className="act-error-message">{error}</div>}

            <button
              className="act-primary-btn"
              onClick={handleStartSession}
              disabled={loading}
            >
              {loading ? 'Starting...' : 'Start'}
            </button>
          </section>
        </main>
      </div>
    );
  }

  // Chat View
  if (!session) return null;

  // Helper to convert OpenAI's default LaTeX delimiters to standard Markdown ones for remark-math
  const processMathDelimiters = (text: string) => {
    if (!text) return text;
    return text
      .replace(/\\\[/g, '$$$$')
      .replace(/\\\]/g, '$$$$')
      .replace(/\\\(/g, '$')
      .replace(/\\\)/g, '$');
  };

  if (isVoiceAssessment) {
    const statusLabel = {
      idle: 'Ready',
      connecting: 'Connecting...',
      listening: 'Listening...',
      speaking: 'Speaking...',
      connected: 'Ready',
      error: 'Needs attention'
    }[voiceStatus];
    const voiceLevelStyle = { '--voice-level': voiceLevel.toFixed(3) } as CSSProperties;

    return (
      <div className="act-app-shell">
        <div className="act-app-header">
          <div className="act-brand">{activePrototypeUI?.title || 'Voice Assessment'}</div>
        </div>
        <main className="act-main">
          <section className="act-voice-card act-card">
            <p className="act-voice-disclosure">You are speaking with an AI-generated voice tutor, not a human.</p>
            <div
              className={`act-voice-orb-stage act-voice-orb-stage-${voiceStatus}`}
              style={voiceLevelStyle}
              aria-label={statusLabel}
              role="img"
            >
              <div className="act-voice-ring act-voice-ring-one" />
              <div className="act-voice-ring act-voice-ring-two" />
              <div className="act-voice-ring act-voice-ring-three" />
              <div className="act-voice-particles" aria-hidden="true">
                <span />
                <span />
                <span />
                <span />
                <span />
                <span />
              </div>
              <div className={`act-voice-orb act-voice-orb-${voiceStatus}`}>
                <span className="act-voice-orb-shine" />
              </div>
              <div className="act-voice-waveform" aria-hidden="true">
                <span />
                <span />
                <span />
                <span />
                <span />
                <span />
                <span />
              </div>
            </div>
            <div className={`act-voice-status-label act-voice-status-label-${voiceStatus}`}>{statusLabel}</div>
            <h1>{voiceStatus === 'speaking' ? 'Tutor speaking' : voiceStatus === 'listening' ? 'Listening closely' : statusLabel}</h1>
            <p>
              Click start, allow microphone access, and answer the tutor out loud. Scores update as the voice model evaluates the conversation.
            </p>
            <div className="act-voice-controls">
              <button
                className="act-primary-btn"
                onClick={handleStartVoiceChat}
                disabled={voiceActive || voiceStatus === 'connecting'}
              >
                {voiceStatus === 'connecting' ? 'Connecting...' : 'Start Voice Chat'}
              </button>
              <button
                className="act-secondary-btn"
                onClick={handleStopVoiceChat}
                disabled={!voiceActive}
              >
                End Voice Chat
              </button>
            </div>
            {error && <div className="act-error-message">{error}</div>}
            {voiceLog.length > 0 && (
              <div className="act-voice-log">
                {voiceLog.map((entry, index) => <div key={`${entry}-${index}`}>{entry}</div>)}
              </div>
            )}
          </section>

          <section className="act-score-dock act-card">
            <div className="act-score-header">
              <span>Assessment Scores</span>
              <button
                className="act-save-score-btn"
                onClick={handleSaveScore}
                disabled={!assessmentData || savingScore}
              >
                {savingScore ? 'Saving...' : 'Save Score'}
              </button>
            </div>
            <div className="act-score-row">
              <span>Engagement</span>
              <div className="act-score-track">
                <div className="act-score-fill act-score-fill-engagement" style={{ width: `${assessmentData?.engagement_score || 0}%` }} />
              </div>
              <strong>{assessmentData?.engagement_score ?? '--'}/100</strong>
            </div>
            <div className="act-score-row">
              <span>Understanding</span>
              <div className="act-score-track">
                <div className="act-score-fill act-score-fill-understanding" style={{ width: `${assessmentData?.score || 0}%` }} />
              </div>
              <strong>{assessmentData?.score ?? '--'}/100</strong>
            </div>
            {assessmentData?.tip && <p className="act-score-tip"><strong>Tip:</strong> {assessmentData.tip}</p>}
          </section>
        </main>
      </div>
    );
  }

  return (
    <div className="act-app-shell">
      <div className="act-app-header">
        <div className="act-brand">{activePrototypeUI?.title || 'Chat'}</div>
      </div>
      <main className="act-main relative">
        <div className="act-chat-messages" style={{ paddingBottom: `${composerHeight + 20}px` }}>
          {session.messages.filter(m => m.role !== 'system').map(m => (
            <div key={m.id} className={`act-message-row act-message-row-${m.role}`}>
              <div className={`act-bubble act-bubble-${m.role} markdown-content`}>
                <ReactMarkdown
                  remarkPlugins={[remarkGfm, remarkMath]}
                  rehypePlugins={[rehypeKatex]}
                  components={{
                    a: (props) => (
                      <a {...props} target="_blank" rel="noopener noreferrer" />
                    )
                  }}
                >
                  {processMathDelimiters(m.content)}
                </ReactMarkdown>
              </div>
            </div>
          ))}
          {loading && (
             <div className="act-message-row act-message-row-assistant">
             <div className="act-bubble act-bubble-assistant opacity-50">
               Thinking...
             </div>
           </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {!activePrototypeUI?.readonly && (
          <div className="act-composer-wrap" ref={composerWrapRef}>
            <div className="act-composer">
              <textarea
                placeholder={activePrototypeUI?.placeholder || 'Type your message...'}
                value={inputValue}
                onChange={e => setInputValue(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                rows={1}
              />
              <button
                className="act-send-btn"
                onClick={handleSend}
                disabled={loading || !inputValue.trim()}
              >
                Send
              </button>
            </div>
            {assessmentData && (
              <div className="act-score-bar-container" style={{
                marginTop: '12px',
                display: 'flex',
                flexDirection: 'column',
                gap: '12px',
                width: '100%',
                backgroundColor: 'var(--surface)',
                padding: '12px 16px',
                borderRadius: '8px',
                border: '1px solid var(--border)'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 'bold', color: '#333' }}>Score</span>
                  <button
                    style={{
                      padding: '6px 12px',
                      fontSize: '14px',
                      width: 'auto',
                      backgroundColor: '#1E3A8A',
                      color: 'white',
                      border: 'none',
                      borderRadius: '6px',
                      cursor: savingScore ? 'not-allowed' : 'pointer',
                      opacity: savingScore ? 0.7 : 1
                    }}
                    onClick={handleSaveScore}
                    disabled={savingScore}
                  >
                    {savingScore ? 'Saving...' : 'Save Score'}
                  </button>
                </div>

                {/* Engagement Score Bar */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <span style={{ width: '100px', fontSize: '14px', color: '#666' }}>Engagement</span>
                  <div style={{
                    flex: 1,
                    height: '10px',
                    backgroundColor: 'var(--bg-main)',
                    borderRadius: '5px',
                    overflow: 'hidden'
                  }}>
                    <div style={{
                      width: `${assessmentData.engagement_score}%`,
                      height: '100%',
                      backgroundColor: '#DC2626', // Red
                      transition: 'width 0.3s ease'
                    }}></div>
                  </div>
                  <span style={{ width: '45px', textAlign: 'right', fontSize: '14px', fontWeight: 'bold', color: '#DC2626' }}>
                    {assessmentData.engagement_score}/100
                  </span>
                </div>

                {/* Understanding Score Bar */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <span style={{ width: '100px', fontSize: '14px', color: '#666' }}>Understanding</span>
                  <div style={{
                    flex: 1,
                    height: '10px',
                    backgroundColor: 'var(--bg-main)',
                    borderRadius: '5px',
                    overflow: 'hidden'
                  }}>
                    <div style={{
                      width: `${assessmentData.score}%`,
                      height: '100%',
                      backgroundColor: '#1E3A8A', // Blue
                      transition: 'width 0.3s ease'
                    }}></div>
                  </div>
                  <span style={{ width: '45px', textAlign: 'right', fontSize: '14px', fontWeight: 'bold', color: '#1E3A8A' }}>
                    {assessmentData.score}/100
                  </span>
                </div>

                {assessmentData.tip && (
                  <div style={{ fontSize: '12px', color: '#888', marginTop: '4px' }}>
                    <span style={{ fontWeight: 'bold' }}>Tip:</span> {assessmentData.tip}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
