import { useState, useEffect, useRef } from 'react';
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
    mode?: 'chat' | 'voice_assessment' | 'sketch' | 'course_factory';
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
  assessment_objectives?: string[];
};

type AssessmentData = {
  sub_objective_scores: number[];
  current_sub_objective_index: number;
  summary: string;
  tip?: string;
};

type VoiceStatus = 'idle' | 'connecting' | 'listening' | 'speaking' | 'connected' | 'error';

type CourseLesson = {
  lesson_id: string;
  lesson_title: string;
  learning_objective: { objective_id: string; objective_text: string };
  activation: { activation_id: string; activation_text: string };
};

type CourseUnit = {
  unit_id: string;
  unit_title: string;
  unit_description: string;
  lessons: CourseLesson[];
};

type CourseOutline = {
  subject: string;
  units: CourseUnit[];
};

type PenColor = 'black' | 'red' | 'green' | 'blue' | 'erase';

type AssessmentToolArgs = {
  current_sub_objective_index?: number | string;
  sub_objective_scores?: Array<number | string>;
  understanding_score?: number | string;
  engagement_score?: number | string;
  summary?: string;
  tip?: string;
};

type RealtimeFunctionCall = {
  type?: string;
  name?: string;
  call_id?: string;
  arguments?: string;
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
  const [courseLogs, setCourseLogs] = useState<string[]>([]);
  const [courseResult, setCourseResult] = useState<CourseOutline | null>(null);
  const [expandedCourseUnits, setExpandedCourseUnits] = useState<Set<string>>(new Set());
  const [expandedCourseLessons, setExpandedCourseLessons] = useState<Set<string>>(new Set());

  // Ref for auto-scrolling
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // State for the assessment prototype specific UI
  const [assessmentData, setAssessmentData] = useState<AssessmentData | null>(null);
  const assessmentDataRef = useRef<AssessmentData | null>(null);
  const [savingScore, setSavingScore] = useState(false);

  const peerConnectionRef = useRef<RTCPeerConnection | null>(null);
  const dataChannelRef = useRef<RTCDataChannel | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null);
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus>('idle');
  const voiceStatusRef = useRef<VoiceStatus>('idle');
  const [voiceActive, setVoiceActive] = useState(false);
  const pushToTalkActiveRef = useRef(false);
  const completedToolCallIdsRef = useRef<Set<string>>(new Set());

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const isDrawingRef = useRef(false);
  const [penColor, setPenColor] = useState<PenColor>('black');

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
    assessmentDataRef.current = assessmentData;
  }, [assessmentData]);

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

  const resetVoiceConnection = () => {
    dataChannelRef.current?.close();
    peerConnectionRef.current?.close();
    localStreamRef.current?.getTracks().forEach(track => track.stop());
    dataChannelRef.current = null;
    peerConnectionRef.current = null;
    localStreamRef.current = null;
    remoteAudioRef.current = null;
    pushToTalkActiveRef.current = false;
    completedToolCallIdsRef.current.clear();
    setVoiceActive(false);
    setVoiceStatus('idle');
  };

  useEffect(() => {
    return () => resetVoiceConnection();
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
           sub_objective_scores: [chatResponse.structured_data.score, engagementScore, 0],
           current_sub_objective_index: 0,
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
  const isSketch = activePrototypeUI?.mode === 'sketch';
  const isCourseFactory = activePrototypeUI?.mode === 'course_factory';


  useEffect(() => {
    if (view !== 'chat' || !isSketch || !canvasRef.current) return;

    const canvas = canvasRef.current;
    const context = canvas.getContext('2d');
    if (!context) return;
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, canvas.width, canvas.height);
  }, [view, isSketch]);

  const getSelectedLessonTopicTitle = () => {
    const lessonTopicInput = activePrototypeUI?.inputs.find(input => input.id === 'lesson_code' || input.label.toLowerCase().includes('topic'));
    const fullTopicTitle = lessonTopicInput?.options?.find(option => option.value === inputValues[lessonTopicInput.id])?.label
      || (lessonTopicInput ? inputValues[lessonTopicInput.id] : '')
      || 'this topic';

    const [, ...topicDetails] = fullTopicTitle.split('-');
    return topicDetails.join('-').trim() || fullTopicTitle.trim();
  };

  const getSketchQuestionInput = () => activePrototypeUI?.inputs.find(input => input.id === 'question');

  const getSketchQuestionValue = () => {
    const questionInput = getSketchQuestionInput();
    return questionInput ? inputValues[questionInput.id] : '';
  };

  const getSketchQuestion = () => {
    const questionInput = getSketchQuestionInput();
    const selectedValue = getSketchQuestionValue();
    return questionInput?.options?.find(option => option.value === selectedValue)?.label
      || selectedValue
      || 'Why do the seasons occur on Earth?';
  };

  const getSketchCoachingFocus = () => {
    if (getSketchQuestionValue() === 'function_shapes_xy_plane') {
      return [
        'This is a high school math sketching task about function shapes on an XY coordinate plane.',
        'Start by asking the student to sketch the function shapes on axes and explain what each curve represents.',
        'Evaluate the drawing against the explanation: look for correctly labeled axes, a straight line for a linear function, U-shaped parabola for a quadratic, J-shaped rapid growth or decay for an exponential, and V-shape for an absolute value function.',
        'Coach with short questions about intercepts, slope, vertex, curvature, symmetry, and growth patterns. Do not simply draw or list the correct answer for the student.'
      ].join('\n');
    }

    return 'This is a high school science sketching task about Earth’s seasons. Focus on axial tilt, sunlight angle, day length, orbit position, and the common distance-from-the-Sun misconception.';
  };

  const getVoiceLessonContext = () => {
    const systemContent = session?.messages.find(message => message.role === 'system')?.content || '';
    const lessonContextMatch = systemContent.match(/(?:^|\n)\[fetchLessonData\]\n([\s\S]*?)(?=\n\n\[|$)/);

    return lessonContextMatch?.[1]?.trim() || `LESSON DATA:\nTopic: ${getSelectedLessonTopicTitle()}`;
  };

  const buildInitialVoiceInstructions = () => {
    if (isSketch) {
      return [
        'You are SKETCH, a realtime drawing coach for a high school science student.',
        `Question: ${getSketchQuestion()}`,
        'The student will draw on a whiteboard and explain their thinking aloud. Use both the latest canvas image and the spoken explanation.',
        'Your goal is to help the student make an accurate, realistic drawing and explanation for a high school level.',
        'Do not score the student. Do not save anything. Do not give the answer or tell the student exactly what to draw.',
        'Respond only with one short coaching question, probing question, or hint. Keep it warm and concise.',
        `Selected prompt coaching focus:
${getSketchCoachingFocus()}`
      ].join('\n\n');
    }

    return [
    'Start the voice assessment with a brief greeting, then ask exactly one focused first assessment question.',
    `Selected lesson topic: ${getSelectedLessonTopicTitle()}`,
    `Backend lesson context:\n${getVoiceLessonContext()}`,
    `Assessment sub-objectives:\n${getAssessmentObjectives().map((objective, index) => `${index + 1}. ${objective}`).join('\n')}`,
    'Begin with sub-objective 1. The first question must be specific to sub-objective 1 and the selected lesson topic. Do not ask a generic question like “tell me one thing you know about this lesson.”'
    ].join('\n\n');
  };

  const getAssessmentObjectives = () => {
    const objectives = session?.assessment_objectives?.filter(Boolean) || [];
    if (objectives.length >= 3) return objectives.slice(0, 3);

    return [
      `Identify the key idea in ${getSelectedLessonTopicTitle()}.`,
      `Explain how ${getSelectedLessonTopicTitle()} works.`,
      `Apply ${getSelectedLessonTopicTitle()} independently.`
    ];
  };

  const clampScore = (value: number | string | undefined) => Math.max(0, Math.min(100, Number(value) || 0));

  const getAssessmentScores = () => {
    const scores = assessmentData?.sub_objective_scores || [];
    return [0, 1, 2].map(index => clampScore(scores[index] || 0));
  };

  const isAssessmentComplete = () => getAssessmentScores().every(score => score >= 85);

  const handleStartVoiceChat = async () => {
    if (!session || voiceStatus === 'connecting') return;

    resetVoiceConnection();
    setError('');
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
      };

      const mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      localStreamRef.current = mediaStream;
      const [localAudioTrack] = mediaStream.getAudioTracks();
      if (localAudioTrack) {
        localAudioTrack.enabled = false;
        pc.addTrack(localAudioTrack);
      }

      const dc = pc.createDataChannel('oai-events');
      dataChannelRef.current = dc;

      dc.addEventListener('open', () => {
        setVoiceActive(true);
        setVoiceStatus('connected');
        dc.send(JSON.stringify({
          type: 'response.create',
          response: {
            instructions: buildInitialVoiceInstructions()
          }
        }));
      });

      dc.addEventListener('message', (event) => {
        const realtimeEvent = JSON.parse(event.data);

        if (realtimeEvent.type === 'response.audio.delta') {
          setVoiceStatus('speaking');
        }
        if (realtimeEvent.type === 'response.done') {
          const assessmentToolCall = realtimeEvent.response?.output?.find((item: RealtimeFunctionCall) => (
            item.type === 'function_call' && item.name === 'update_assessment_scores'
          ));

          if (assessmentToolCall) {
            const args = JSON.parse(assessmentToolCall.arguments || '{}');
            completeAssessmentToolCall(assessmentToolCall.call_id, args);
            applyAssessmentToolArgs(args);
          } else if (!pushToTalkActiveRef.current) {
            setVoiceStatus('connected');
          }
        }
        if (
          realtimeEvent.type === 'response.function_call_arguments.done' &&
          realtimeEvent.name === 'update_assessment_scores'
        ) {
          // Wait for response.done before completing the tool call so we can
          // update the UI and trigger exactly one verbal follow-up.
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

  const setLocalMicrophoneEnabled = (enabled: boolean) => {
    localStreamRef.current?.getAudioTracks().forEach(track => {
      track.enabled = enabled;
    });
  };

  const buildAssessmentDataFromToolArgs = (args: AssessmentToolArgs): AssessmentData => {
    const previousScores = assessmentDataRef.current?.sub_objective_scores || [0, 0, 0];
    const scores = args.sub_objective_scores?.length
      ? [0, 1, 2].map(index => clampScore(args.sub_objective_scores?.[index]))
      : [clampScore(args.understanding_score), clampScore(previousScores[1]), clampScore(previousScores[2])];
    const firstIncompleteIndex = scores.findIndex(score => score < 85);

    return {
      sub_objective_scores: scores,
      current_sub_objective_index: firstIncompleteIndex === -1 ? 2 : firstIncompleteIndex,
      summary: args.summary || assessmentDataRef.current?.summary || '',
      tip: args.tip
    };
  };

  const applyAssessmentToolArgs = (args: AssessmentToolArgs) => {
    const nextAssessmentData = buildAssessmentDataFromToolArgs(args);
    assessmentDataRef.current = nextAssessmentData;
    setAssessmentData(nextAssessmentData);
  };

  const completeAssessmentToolCall = (callId: string | undefined, args: AssessmentToolArgs) => {
    const dc = dataChannelRef.current;
    if (!callId || !dc || dc.readyState !== 'open' || completedToolCallIdsRef.current.has(callId)) return;
    completedToolCallIdsRef.current.add(callId);

    const previousScores = assessmentDataRef.current?.sub_objective_scores || [0, 0, 0];
    const nextAssessmentData = buildAssessmentDataFromToolArgs(args);
    const objectives = getAssessmentObjectives();
    const scores = nextAssessmentData.sub_objective_scores;
    const completedIndex = scores.findIndex((score, index) => score >= 85 && (previousScores[index] || 0) < 85);
    const nextIncompleteIndex = scores.findIndex(score => score < 85);
    const allComplete = nextIncompleteIndex === -1;

    dc.send(JSON.stringify({
      type: 'conversation.item.create',
      item: {
        type: 'function_call_output',
        call_id: callId,
        output: JSON.stringify({
          ok: true,
          displayed_to_student: {
            current_sub_objective_index: nextAssessmentData.current_sub_objective_index,
            sub_objective_scores: scores,
            summary: nextAssessmentData.summary,
            tip: nextAssessmentData.tip || '',
            submit_enabled: allComplete
          }
        })
      }
    }));

    const transitionInstruction = allComplete
      ? 'All three sub-objectives are mastered. Briefly congratulate the student and tell them they can submit the assessment now.'
      : completedIndex !== -1
        ? `Acknowledge that the student met sub-objective ${completedIndex + 1}: "${objectives[completedIndex]}". Then transition to sub-objective ${nextIncompleteIndex + 1}: "${objectives[nextIncompleteIndex]}" and ask one focused question about it.`
        : `Give brief supportive feedback and ask one focused follow-up question about current sub-objective ${nextIncompleteIndex + 1}: "${objectives[nextIncompleteIndex]}".`;

    dc.send(JSON.stringify({
      type: 'response.create',
      response: {
        instructions: transitionInstruction
      }
    }));
  };

  const sendSketchCanvasSnapshot = () => {
    if (!isSketch || !canvasRef.current || !dataChannelRef.current || dataChannelRef.current.readyState !== 'open') return;

    dataChannelRef.current.send(JSON.stringify({
      type: 'conversation.item.create',
      item: {
        type: 'message',
        role: 'user',
        content: [
          {
            type: 'input_text',
            text: `Here is my current drawing for: ${getSketchQuestion()}`
          },
          {
            type: 'input_image',
            image_url: canvasRef.current.toDataURL('image/png')
          }
        ]
      }
    }));
  };

  const handlePointerDownCanvas = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context) return;

    const rect = canvas.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * canvas.width;
    const y = ((event.clientY - rect.top) / rect.height) * canvas.height;
    isDrawingRef.current = true;
    canvas.setPointerCapture(event.pointerId);
    context.beginPath();
    context.moveTo(x, y);
  };

  const handlePointerMoveCanvas = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!isDrawingRef.current) return;
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context) return;

    const rect = canvas.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * canvas.width;
    const y = ((event.clientY - rect.top) / rect.height) * canvas.height;
    context.strokeStyle = penColor === 'erase' ? '#ffffff' : penColor;
    context.lineWidth = penColor === 'erase' ? 28 : 5;
    context.lineCap = 'round';
    context.lineJoin = 'round';
    context.lineTo(x, y);
    context.stroke();
  };

  const handlePointerUpCanvas = (event: React.PointerEvent<HTMLCanvasElement>) => {
    isDrawingRef.current = false;
    canvasRef.current?.releasePointerCapture(event.pointerId);
  };

  const handleClearCanvas = () => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context) return;
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, canvas.width, canvas.height);
  };

  const handlePushToTalkStart = () => {
    if (!voiceActive || voiceStatus === 'connecting' || voiceStatus === 'error') return;
    sendSketchCanvasSnapshot();
    pushToTalkActiveRef.current = true;
    setLocalMicrophoneEnabled(true);
    setVoiceStatus('listening');
  };

  const handlePushToTalkEnd = () => {
    if (!voiceActive) return;
    pushToTalkActiveRef.current = false;
    setLocalMicrophoneEnabled(false);
    if (voiceStatusRef.current === 'listening') {
      setVoiceStatus('connected');
    }
  };

  const handleStopVoiceChat = () => {
    resetVoiceConnection();
  };

  const handleSaveScore = async () => {
    if (!session || !assessmentData || savingScore || !isAssessmentComplete()) return;
    setSavingScore(true);
    try {
      const scores = getAssessmentScores();
      const subObjectives = getAssessmentObjectives().map((objective, index) => ({
        objective,
        score: scores[index],
        mastered: scores[index] >= 85
      }));
      const res = await fetch(`${API_BASE}/chat/save-score`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: inputValues['user_id'] || 'unknown',
          lesson_topic: inputValues['lesson_code'] || 'unknown',
          score: Math.round(scores.reduce((total, score) => total + score, 0) / scores.length),
          summary: assessmentData.summary || 'The student met all three formative assessment sub-objectives.',
          sub_objectives: subObjectives
        })
      });
      if (!res.ok) throw new Error('Failed to save score');
      alert('Assessment submitted successfully!');
    } catch (e: unknown) {
      alert(`Error saving score: ${getErrorMessage(e)}`);
    } finally {
      setSavingScore(false);
    }
  };


  const downloadTextFile = (filename: string, content: string, mimeType: string) => {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const courseToCsv = (course: CourseOutline) => {
    const rows = [['subject', 'unit_id', 'unit_title', 'lesson_id', 'lesson_title', 'objective_id', 'objective_text', 'activation_id', 'activation_text']];
    course.units.forEach(unit => {
      unit.lessons.forEach(lesson => {
        rows.push([
          course.subject,
          unit.unit_id,
          unit.unit_title,
          lesson.lesson_id,
          lesson.lesson_title,
          lesson.learning_objective.objective_id,
          lesson.learning_objective.objective_text,
          lesson.activation.activation_id,
          lesson.activation.activation_text
        ]);
      });
    });
    return rows.map(row => row.map(value => `"${String(value).replace(/"/g, '""')}"`).join(',')).join('\n');
  };

  const handleGenerateCourse = () => {
    const subject = inputValues.subject?.trim();
    if (!subject) {
      setError('Please enter a course subject.');
      return;
    }

    setError('');
    setLoading(true);
    setCourseResult(null);
    setCourseLogs([]);

    const events = new EventSource(`${API_BASE}/course-factory/stream?subject=${encodeURIComponent(subject)}`);
    events.addEventListener('log', event => {
      const payload = JSON.parse((event as MessageEvent).data);
      setCourseLogs(previous => [...previous, payload.message]);
    });
    events.addEventListener('complete', event => {
      const payload = JSON.parse((event as MessageEvent).data);
      setCourseResult(payload.course);
      setExpandedCourseUnits(new Set([payload.course.units?.[0]?.unit_id].filter(Boolean)));
      setExpandedCourseLessons(new Set());
      setLoading(false);
      events.close();
    });
    events.addEventListener('error', event => {
      if ((event as MessageEvent).data) {
        const payload = JSON.parse((event as MessageEvent).data);
        setError(payload.message || 'Course generation failed.');
      } else {
        setError('Course generation failed.');
      }
      setLoading(false);
      events.close();
    });
  };

  const handleGenerateAnotherCourse = () => {
    setCourseLogs([]);
    setCourseResult(null);
    setExpandedCourseUnits(new Set());
    setExpandedCourseLessons(new Set());
    setError('');
  };



  const toggleCourseUnit = (unitId: string) => {
    setExpandedCourseUnits(previous => {
      const next = new Set(previous);
      if (next.has(unitId)) {
        next.delete(unitId);
      } else {
        next.add(unitId);
      }
      return next;
    });
  };

  const toggleCourseLesson = (lessonId: string) => {
    setExpandedCourseLessons(previous => {
      const next = new Set(previous);
      if (next.has(lessonId)) {
        next.delete(lessonId);
      } else {
        next.add(lessonId);
      }
      return next;
    });
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


  if (view === 'splash' && activePrototypeUI && isCourseFactory) {
    return (
      <div className="act-app-shell">
        <div className="act-app-header">
          <div className="act-brand">Course Factory</div>
        </div>
        <main className="act-main">
          {!courseResult && (
            <section className="act-welcome-card act-course-card">
              <h1>Course Factory</h1>
              <p>Let's make a course about ...</p>
              <div className="act-form-row">
                <label>Course subject</label>
                <input
                  type="text"
                  placeholder={activePrototypeUI.placeholder || 'Introductory Astronomy'}
                  value={inputValues.subject || ''}
                  onChange={e => updateInputValue('subject', e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter') handleGenerateCourse();
                  }}
                />
              </div>
              {error && <div className="act-error-message">{error}</div>}
              <button className="act-primary-btn" onClick={handleGenerateCourse} disabled={loading}>
                {loading ? 'Generating...' : 'Generate Course'}
              </button>
            </section>
          )}

          {loading && courseLogs.length > 0 && !courseResult && (
            <section className="act-card act-course-log" aria-live="polite">
              <h2>Process Log</h2>
              <ol>
                {courseLogs.map((log, index) => <li key={`${log}-${index}`}>{log}</li>)}
                {loading && <li className="act-log-active">Agents are working...</li>}
              </ol>
            </section>
          )}

          {courseResult && (
            <section className="act-card act-course-results">
              <div className="act-course-results-header">
                <p className="act-eyebrow">Completed Course Outline</p>
                <h1>{courseResult.subject}</h1>
                <p className="act-course-results-subtitle">Eight sequenced units with lesson-level objectives and activations.</p>
              </div>

              <div className="act-course-accordion">
                {courseResult.units.map((unit, unitIndex) => {
                  const unitOpen = expandedCourseUnits.has(unit.unit_id);

                  return (
                    <article key={unit.unit_id} className={`act-unit-panel ${unitOpen ? 'act-panel-open' : ''}`}>
                      <button
                        className="act-unit-toggle"
                        onClick={() => toggleCourseUnit(unit.unit_id)}
                        aria-expanded={unitOpen}
                        type="button"
                      >
                        <span className="act-unit-kicker">Unit {unitIndex + 1}</span>
                        <span className="act-unit-title">{unit.unit_title}</span>
                        <span className="act-panel-icon" aria-hidden="true">{unitOpen ? '−' : '+'}</span>
                      </button>

                      {unitOpen && (
                        <div className="act-unit-body">
                          {unit.unit_description && <p className="act-unit-description">{unit.unit_description}</p>}
                          <div className="act-lesson-list">
                            {unit.lessons.map((lesson, lessonIndex) => {
                              const lessonOpen = expandedCourseLessons.has(lesson.lesson_id);

                              return (
                                <div key={lesson.lesson_id} className={`act-lesson-panel ${lessonOpen ? 'act-panel-open' : ''}`}>
                                  <button
                                    className="act-lesson-toggle"
                                    onClick={() => toggleCourseLesson(lesson.lesson_id)}
                                    aria-expanded={lessonOpen}
                                    type="button"
                                  >
                                    <span className="act-lesson-number">Lesson {lessonIndex + 1}</span>
                                    <span className="act-lesson-title">{lesson.lesson_title}</span>
                                    <span className="act-panel-icon" aria-hidden="true">{lessonOpen ? '−' : '+'}</span>
                                  </button>

                                  {lessonOpen && (
                                    <div className="act-lesson-content">
                                      <div className="act-content-block">
                                        <h3>Learning Objective</h3>
                                        <p>{lesson.learning_objective.objective_text}</p>
                                      </div>
                                      <div className="act-content-block act-activation-block">
                                        <h3>Activation</h3>
                                        <p>{lesson.activation.activation_text}</p>
                                      </div>
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>

              <div className="act-course-actions">
                <button className="act-secondary-btn" onClick={() => downloadTextFile(`${courseResult.subject}.json`, JSON.stringify(courseResult, null, 2), 'application/json')}>Download JSON</button>
                <button className="act-secondary-btn" onClick={() => downloadTextFile(`${courseResult.subject}.csv`, courseToCsv(courseResult), 'text/csv')}>Download CSV</button>
                <button className="act-primary-btn" onClick={handleGenerateAnotherCourse}>Generate Another Course</button>
              </div>
            </section>
          )}
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

  if (isVoiceAssessment || isSketch) {
    const statusLabel = {
      idle: 'Disconnected',
      connecting: 'Connecting',
      listening: 'Listening',
      speaking: 'Speaking',
      connected: 'Waiting',
      error: 'Needs attention'
    }[voiceStatus];
    const topicTitle = isSketch ? getSketchQuestion() : getSelectedLessonTopicTitle();

    return (
      <div className="act-app-shell">
        <div className="act-app-header">
          <div className="act-brand">{isSketch ? 'Realtime Drawing Coach' : 'Voice-Based Formative Assessment'}</div>
        </div>
        <main className="act-main">
          <section className="act-voice-card act-card">
            <div className="act-voice-intro">
              <h1>{isSketch ? "Hi, I'm SKETCH." : "Hi, I'm ALEX."}</h1>
              <p>{isSketch ? "Let's draw some pictures." : `Let's have a conversation about ${topicTitle}.`}</p>
            </div>
            <div className={`act-voice-status-label act-voice-status-label-${voiceStatus}`}>{statusLabel}</div>
            <div className="act-voice-controls">
              <button
                className="act-primary-btn"
                onClick={voiceActive ? undefined : handleStartVoiceChat}
                onPointerDown={voiceActive ? handlePushToTalkStart : undefined}
                onPointerUp={voiceActive ? handlePushToTalkEnd : undefined}
                onPointerLeave={voiceActive ? handlePushToTalkEnd : undefined}
                onPointerCancel={voiceActive ? handlePushToTalkEnd : undefined}
                onKeyDown={voiceActive ? (event) => {
                  if (event.key === ' ' || event.key === 'Enter') {
                    event.preventDefault();
                    handlePushToTalkStart();
                  }
                } : undefined}
                onKeyUp={voiceActive ? (event) => {
                  if (event.key === ' ' || event.key === 'Enter') {
                    event.preventDefault();
                    handlePushToTalkEnd();
                  }
                } : undefined}
                aria-label={voiceActive ? 'Push and hold to talk' : 'Start voice chat'}
                disabled={voiceStatus === 'connecting'}
                type="button"
              >
                {voiceStatus === 'connecting' ? 'Connecting...' : voiceActive ? 'Push to Talk' : 'Start Voice Chat'}
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
          </section>

          {isSketch ? (
            <section className="act-sketch-dock act-card">
              <div className="act-sketch-toolbar" aria-label="Drawing tools">
                {(['black', 'red', 'green', 'blue'] as PenColor[]).map(color => (
                  <button
                    key={color}
                    className={`act-color-btn ${penColor === color ? 'act-color-btn-active' : ''}`}
                    style={{ backgroundColor: color }}
                    onClick={() => setPenColor(color)}
                    aria-label={`${color} pen`}
                    type="button"
                  />
                ))}
                <button
                  className={`act-eraser-btn ${penColor === 'erase' ? 'act-eraser-btn-active' : ''}`}
                  onClick={() => setPenColor('erase')}
                  type="button"
                >
                  Erase
                </button>
                <button className="act-clear-btn" onClick={handleClearCanvas} type="button">Clear</button>
              </div>
              <canvas
                ref={canvasRef}
                className="act-sketch-canvas"
                width={1200}
                height={650}
                onPointerDown={handlePointerDownCanvas}
                onPointerMove={handlePointerMoveCanvas}
                onPointerUp={handlePointerUpCanvas}
                onPointerCancel={handlePointerUpCanvas}
                onPointerLeave={() => { isDrawingRef.current = false; }}
                aria-label="Drawing canvas"
              />
            </section>
          ) : (
            <section className="act-score-dock act-card">
              <div className="act-score-header">
                <span>Assessment Steps</span>
              </div>
              <div className="act-objective-list">
                {getAssessmentObjectives().map((objective, index) => {
                  const score = getAssessmentScores()[index];
                  const mastered = score >= 85;

                  return (
                    <div className="act-objective-score" key={`${objective}-${index}`}>
                      <p className="act-objective-text">{objective}</p>
                      <div className="act-objective-score-row">
                        <div className="act-score-track act-score-track-objective" aria-label={`${objective} score`}>
                          <div className="act-score-fill act-score-fill-objective" style={{ width: `${score}%` }} />
                        </div>
                        <strong>{score}/100</strong>
                        <span className={`act-objective-check ${mastered ? 'act-objective-check-complete' : ''}`} aria-label={mastered ? 'Mastered' : 'Not yet mastered'}>✓</span>
                      </div>
                    </div>
                  );
                })}
              </div>
              <button className="act-submit-assessment-btn" onClick={handleSaveScore} disabled={!isAssessmentComplete() || savingScore}>
                {savingScore ? 'Submitting...' : 'Submit'}
              </button>
            </section>
          )}
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
                      width: `${assessmentData.sub_objective_scores[1]}%`,
                      height: '100%',
                      backgroundColor: '#DC2626', // Red
                      transition: 'width 0.3s ease'
                    }}></div>
                  </div>
                  <span style={{ width: '45px', textAlign: 'right', fontSize: '14px', fontWeight: 'bold', color: '#DC2626' }}>
                    {assessmentData.sub_objective_scores[1]}/100
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
                      width: `${assessmentData.sub_objective_scores[0]}%`,
                      height: '100%',
                      backgroundColor: '#1E3A8A', // Blue
                      transition: 'width 0.3s ease'
                    }}></div>
                  </div>
                  <span style={{ width: '45px', textAlign: 'right', fontSize: '14px', fontWeight: 'bold', color: '#1E3A8A' }}>
                    {assessmentData.sub_objective_scores[0]}/100
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
