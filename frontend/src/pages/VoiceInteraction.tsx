import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faMicrophone, faStop, faSpinner, faArrowLeft, faPause, faPlay } from '@fortawesome/free-solid-svg-icons';
import './VoiceInteraction.css';

interface Message {
  role: string;
  query: string;
  response: string;
  timestamp: number;
  audio_base64?: string;
  map_data?: any;
  media_data?: { type: string; url: string };
}

const VoiceInteraction: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [isContinuous, setIsContinuous] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentAudioType, setCurrentAudioType] = useState<'none' | 'preliminary' | 'delay' | 'response'>('none');
  const [queryCount, setQueryCount] = useState(0);
  const socketRef = useRef<WebSocket | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const secondaryTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const silenceTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttempts = useRef<number>(0);
  const maxReconnectAttempts = 3;
  const reconnectInterval = 7000;
  const currentChunksRef = useRef<Blob[]>([]);
  const isSpeakingRef = useRef(false);
  const isSilencePendingRef = useRef(false);
  const rafIdRef = useRef<number | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const dataArrayRef = useRef<Uint8Array | null>(null);

  // Array of preliminary response audio files in sequence
  const preliminaryAudios = [
    '/static/preliminary_response.mp3',
    '/static/preliminary_response_a.mp3',
    '/static/preliminary_response_b.mp3',
    '/static/preliminary_response_c.mp3',
    '/static/preliminary_response_d.mp3',
    '/static/preliminary_response_e.mp3'
  ];

  const getNextPreliminaryAudio = () => {
    const index = queryCount % preliminaryAudios.length;
    return preliminaryAudios[index];
  };

  const connectWebSocket = useCallback(() => {
    if (!sessionId) return;

    socketRef.current = new WebSocket(`ws://localhost:8000/ws/voice/${sessionId}`);
    socketRef.current.onopen = () => {
      console.log(`Voice WebSocket connected for session: ${sessionId}`);
      reconnectAttempts.current = 0;
      setError(null);
      const pingInterval = setInterval(() => {
        if (socketRef.current?.readyState === WebSocket.OPEN) {
          socketRef.current.send(JSON.stringify({ type: 'ping' }));
        }
      }, 30000);
      socketRef.current.onclose = () => clearInterval(pingInterval);
    };

    socketRef.current.onmessage = async (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'pong') {
          console.log('Received pong, Voice WebSocket alive');
          return;
        }
        if (data.error) {
          console.log('Received WS error:', data.error);
          setError(`WebSocket error: ${data.error}`);
          setIsProcessing(false);
          startContinuous();
          // Clear secondary timeout on error
          if (secondaryTimeoutRef.current) {
            clearTimeout(secondaryTimeoutRef.current);
            secondaryTimeoutRef.current = null;
          }
          return;
        }
        // Only process assistant responses with audio_base64
        if (data.audio_base64 && data.role === 'assistant') {
          if (audioRef.current) {
            // Clear any pending secondary timeout
            if (secondaryTimeoutRef.current) {
              clearTimeout(secondaryTimeoutRef.current);
              secondaryTimeoutRef.current = null;
            }
            audioRef.current.src = `data:audio/mpeg;base64,${data.audio_base64}`;
            setCurrentAudioType('response');
            try {
              await audioRef.current.play();
              setIsPlaying(true);
              setIsPaused(false);
            } catch (err: any) {
              if (err.name !== 'AbortError') {
                console.error('Error playing audio:', err);
                setError('Failed to play assistant response.');
              } else {
                console.log('Response play interrupted');
              }
            }
          }
          // Do not setIsProcessing(false) here; moved to handleAudioEnded
        } else {
          console.log('Ignoring non-assistant or non-voice message:', data);
        }
      } catch (err) {
        console.error('Error processing WebSocket message:', err);
        setError('Failed to process incoming voice message.');
        setIsProcessing(false);
        startContinuous();
      }
    };

    socketRef.current.onerror = (err) => {
      console.error('Voice WebSocket error:', err);
      setError('WebSocket connection error. Attempting to reconnect...');
    };

    socketRef.current.onclose = (event) => {
      console.log(`Voice WebSocket closed for session: ${sessionId}`, event);
      if (event.code === 1008) {
        setError(`Session invalid or expired: ${event.reason}`);
      } else if (reconnectAttempts.current < maxReconnectAttempts) {
        reconnectAttempts.current += 1;
        setTimeout(connectWebSocket, reconnectInterval);
      } else {
        setError('Failed to reconnect to voice WebSocket after multiple attempts.');
        setIsProcessing(false);
      }
    };
  }, [sessionId]);

  const startContinuous = useCallback(async () => {
    if (isProcessing) return;
    console.log('Starting continuous listening');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // Setup Web Audio API for VAD
      const audioContext = new AudioContext();
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 512;
      const dataArray = new Uint8Array(analyser.frequencyBinCount);
      source.connect(analyser);

      // Setup MediaRecorder
      const mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      mediaRecorder.ondataavailable = (event) => {
        console.log('Data available, size:', event.data.size, 'speaking:', isSpeakingRef.current, 'silencePending:', isSilencePendingRef.current);
        if (event.data.size > 0 && (isSpeakingRef.current || isSilencePendingRef.current)) {
          currentChunksRef.current.push(event.data);
          console.log('Pushed chunk, total chunks:', currentChunksRef.current.length);
        }
      };
      mediaRecorder.start(250);

      // Set refs
      audioContextRef.current = audioContext;
      sourceRef.current = source;
      analyserRef.current = analyser;
      dataArrayRef.current = dataArray;
      mediaRecorderRef.current = mediaRecorder;
      currentChunksRef.current = [];
      isSpeakingRef.current = false;
      isSilencePendingRef.current = false;
      setIsContinuous(true);
      setIsRecording(false);
      if (silenceTimeoutRef.current) {
        clearTimeout(silenceTimeoutRef.current);
        silenceTimeoutRef.current = null;
      }

      // Analysis loop
      const analyseAudio = () => {
        if (analyserRef.current && dataArrayRef.current) {
          analyserRef.current.getByteTimeDomainData(dataArrayRef.current);
          let sum = 0.0;
          for (let i = 0; i < dataArrayRef.current.length; ++i) {
            const val = dataArrayRef.current[i] / 128.0 - 1.0;
            sum += val * val;
          }
          const rms = Math.sqrt(sum / dataArrayRef.current.length);
          const threshold = 0.02; // Adjustable threshold for voice detection
          const nowSpeaking = rms > threshold;

          if (nowSpeaking) {
            if (!isSpeakingRef.current && !isSilencePendingRef.current) {
              // Start new utterance
              console.log('Voice detected, starting utterance');
              currentChunksRef.current = [];
              isSpeakingRef.current = true;
              setIsRecording(true);
            } else if (isSilencePendingRef.current) {
              // Resume utterance
              console.log('Voice resumed after silence');
              if (silenceTimeoutRef.current) {
                clearTimeout(silenceTimeoutRef.current);
                silenceTimeoutRef.current = null;
              }
              isSilencePendingRef.current = false;
              isSpeakingRef.current = true;
              setIsRecording(true);
            }
          } else {
            if (isSpeakingRef.current) {
              // Potential end of utterance
              console.log('Silence detected, starting 3s timer');
              isSpeakingRef.current = false;
              isSilencePendingRef.current = true;
              setIsRecording(true);
              silenceTimeoutRef.current = setTimeout(() => {
                console.log('3s silence, processing utterance');
                processUtterance();
                isSilencePendingRef.current = false;
                setIsRecording(false);
                isSpeakingRef.current = false;
              }, 3000);
            }
          }
        }
        rafIdRef.current = requestAnimationFrame(analyseAudio);
      };
      rafIdRef.current = requestAnimationFrame(analyseAudio);
    } catch (err: any) {
      console.error('Error starting continuous listening:', err);
      setError('Failed to access microphone. Please check permissions.');
    }
  }, [isProcessing]);

  const stopContinuous = useCallback(() => {
    console.log('Stopping continuous listening');
    setIsContinuous(false);
    setIsRecording(false);
    isSpeakingRef.current = false;
    isSilencePendingRef.current = false;
    if (silenceTimeoutRef.current) {
      clearTimeout(silenceTimeoutRef.current);
      silenceTimeoutRef.current = null;
    }
    if (rafIdRef.current) {
      cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = null;
    }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop();
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    sourceRef.current = null;
    analyserRef.current = null;
    dataArrayRef.current = null;
    currentChunksRef.current = [];
    mediaRecorderRef.current = null;
  }, []);

  const processUtterance = useCallback(async () => {
    console.log('Processing utterance, chunks length:', currentChunksRef.current.length);
    if (currentChunksRef.current.length === 0) {
      console.log('No chunks, aborting process');
      return;
    }

    // Stop the recorder
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop();
    }

    setQueryCount(prev => {
      const newCount = prev + 1;
      console.log(`User query #${newCount}`);
      return newCount;
    });

    setIsProcessing(true);
    stopContinuous(); // Stop continuous during processing

    const audioBlob = new Blob(currentChunksRef.current, { type: 'audio/webm' });
    console.log('Audio blob size:', audioBlob.size);
    const arrayBuffer = await audioBlob.arrayBuffer();
    const base64Audio = btoa(
      new Uint8Array(arrayBuffer).reduce(
        (data, byte) => data + String.fromCharCode(byte),
        ''
      )
    );
    console.log('Base64 length:', base64Audio.length);

    if (base64Audio.length === 0) {
      console.log('Base64 empty, no audio to send');
      setError('No audio recorded. Please try again.');
      setIsProcessing(false);
      startContinuous();
      return;
    }

    if (socketRef.current?.readyState === WebSocket.OPEN) {
      console.log('Sending audio data, length:', base64Audio.length);
      socketRef.current.send(
        JSON.stringify({
          type: 'audio',
          audio_data: base64Audio,
          timestamp: Date.now() / 1000,
          query_count: queryCount + 1
        })
      );

      playPreliminaryResponse();

      // Main timeout for no response
      setTimeout(() => {
        if (isProcessing) {
          setError('No response from server. Please try again.');
          setIsProcessing(false);
          startContinuous();
        }
      }, 15000);
    } else {
      setError('WebSocket is not connected. Please try again.');
      setIsProcessing(false);
      startContinuous();
    }

    currentChunksRef.current = [];
  }, [queryCount]);

  const playPreliminaryResponse = () => {
    if (audioRef.current) {
      const audioPath = getNextPreliminaryAudio();
      console.log(`Playing preliminary audio ${queryCount + 1}: ${audioPath}`);
      audioRef.current.src = audioPath;
      setCurrentAudioType('preliminary');
      audioRef.current.play()
        .then(() => {
          setIsPlaying(true);
          setIsPaused(false);
        })
        .catch((err: any) => {
          if (err.name !== 'AbortError') {
            console.error('Error playing preliminary response:', err);
            setError(`Failed to play preliminary audio: ${audioPath}`);
          } else {
            console.log('Preliminary play interrupted, likely by quick response');
          }
        });
    }
  };

  const playDelayResponse = () => {
    if (audioRef.current) {
      audioRef.current.src = '/static/preliminary_response_1.mp3';
      setCurrentAudioType('delay');
      audioRef.current.play()
        .then(() => {
          setIsPlaying(true);
          setIsPaused(false);
        })
        .catch((err: any) => {
          if (err.name !== 'AbortError') {
            console.error('Error playing delay response:', err);
          } else {
            console.log('Delay play interrupted');
          }
        });
    }
  };

  const toggleContinuous = () => {
    if (isContinuous) {
      stopContinuous();
    } else {
      startContinuous();
    }
  };

  const stopResponse = () => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      setIsPlaying(false);
      setIsPaused(false);
      setCurrentAudioType('none');
      if (secondaryTimeoutRef.current) {
        clearTimeout(secondaryTimeoutRef.current);
        secondaryTimeoutRef.current = null;
      }
    }
  };

  const togglePause = () => {
    if (audioRef.current) {
      if (isPaused) {
        audioRef.current.play();
        setIsPlaying(true);
        setIsPaused(false);
      } else if (isPlaying) {
        audioRef.current.pause();
        setIsPlaying(false);
        setIsPaused(true);
      }
    }
  };

  const handleAudioEnded = () => {
    setIsPlaying(false);
    setIsPaused(false);
    if (isProcessing) {
      if (currentAudioType === 'preliminary') {
        // Set 4-second delay for delay audio
        secondaryTimeoutRef.current = setTimeout(() => {
          if (isProcessing) {
            playDelayResponse();
          }
        }, 4000);
      } else if (currentAudioType === 'delay') {
        // Wait for response
      } else if (currentAudioType === 'response') {
        setIsProcessing(false);
        startContinuous();
      }
    }
    setCurrentAudioType('none');
  };

  const handleBack = () => {
    const token = new URLSearchParams(location.search).get('token');
    navigate(`/candidate-chat?token=${token}`);
  };

  const getStatusText = () => {
    if (isProcessing) return 'Thinking...';
    if (isPlaying) return 'Speaking...';
    if (isPaused) return 'Paused';
    if (isRecording) return 'Listening...';
    if (isContinuous) return 'Ready, speak anytime.';
    return 'Click microphone to enable hands-free listening.';
  };

  const getBlobClass = () => {
    if (isRecording) return 'blob listening';
    if (isProcessing) return 'blob thinking';
    if (isPlaying) return 'blob speaking';
    return 'blob idle';
  };

  useEffect(() => {
    const queryParams = new URLSearchParams(location.search);
    const sessionIdParam = queryParams.get('sessionId');
    const token = queryParams.get('token');
    if (!sessionIdParam || !token) {
      setError('Missing session ID or token. Please access via the chat page.');
      return;
    }
    setSessionId(sessionIdParam);

    const validateToken = async () => {
      try {
        await axios.get('http://localhost:8000/validate-token/', { params: { token } });
      } catch (err: any) {
        console.error('Token validation error:', err);
        setError('Invalid or expired token. Please request a new link.');
      }
    };
    validateToken();

    connectWebSocket();
    startContinuous();

    return () => {
      socketRef.current?.close();
      stopContinuous();
      if (secondaryTimeoutRef.current) {
        clearTimeout(secondaryTimeoutRef.current);
      }
    };
  }, [location.search, connectWebSocket]);

  if (error) {
    return (
      <div className="text-red-500 text-center p-4 bg-black h-screen flex items-center justify-center">
        <div>
          <h2 className="text-lg mb-4">Error</h2>
          <p>{error}</p>
          <button
            onClick={handleBack}
            className="mt-4 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-white"
          >
            Back to Chat
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-black text-white">
      <div className="p-4 flex items-center">
        <button
          onClick={handleBack}
          className="p-2 bg-gray-800 hover:bg-gray-700 text-white rounded-full mr-2"
          title="Back to Chat"
        >
          <FontAwesomeIcon icon={faArrowLeft} />
        </button>
        <img src="/assets/favicon.ico" alt="Quadrant Logo" className="h-8 w-8 mr-2" />
        <h1 className="text-xl font-bold">Voice Interaction</h1>
      </div>
      
      <div className="flex-1 flex flex-col items-center justify-center p-4">
        <div className={getBlobClass()}></div>
        <div className="mt-4 text-gray-400 text-center">
          {getStatusText()}
        </div>
      </div>
      
      <div className="p-4 flex justify-center items-center space-x-4 bg-black">
        <button
          onClick={toggleContinuous}
          disabled={isProcessing || isPlaying || isPaused}
          className={`p-4 rounded-full text-white ${
            isContinuous
              ? 'bg-red-600 hover:bg-red-700'
              : isProcessing
              ? 'bg-gray-600 cursor-not-allowed'
              : 'bg-blue-600 hover:bg-blue-700'
          }`}
          title={isContinuous ? 'Stop continuous listening' : 'Start continuous listening'}
        >
          {isProcessing ? (
            <FontAwesomeIcon icon={faSpinner} spin size="lg" />
          ) : (
            <FontAwesomeIcon icon={faMicrophone} size="lg" />
          )}
        </button>
        <button
          onClick={togglePause}
          disabled={!isPlaying && !isPaused}
          className={`p-4 rounded-full text-white ${
            isPlaying || isPaused ? 'bg-blue-600 hover:bg-blue-700' : 'bg-gray-600 cursor-not-allowed'
          }`}
          title={isPaused ? 'Resume Response' : 'Pause Response'}
        >
          <FontAwesomeIcon icon={isPaused ? faPlay : faPause} size="lg" />
        </button>
        <button
          onClick={stopResponse}
          disabled={!isPlaying && !isPaused}
          className={`p-4 rounded-full text-white ${
            isPlaying || isPaused ? 'bg-red-600 hover:bg-red-700' : 'bg-gray-600 cursor-not-allowed'
          }`}
          title="Stop Response"
        >
          <FontAwesomeIcon icon={faStop} size="lg" />
        </button>
      </div>
      
      <audio
        ref={audioRef}
        onPlay={() => setIsPlaying(true)}
        onEnded={handleAudioEnded}
        onError={(e) => {
          console.error('Audio playback error:', e);
          setError('Failed to play audio file');
          setIsPlaying(false);
        }}
      />
    </div>
  );
};

export default VoiceInteraction;