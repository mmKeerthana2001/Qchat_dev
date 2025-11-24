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
  const [error, setError] = useState<string | null>(null);
  const [currentAudioType, setCurrentAudioType] = useState<'none' | 'preliminary' | 'delay' | 'response'>('none');
  const [queryCount, setQueryCount] = useState(0);
  const [isSpeechDetected, setIsSpeechDetected] = useState(false);
  const [isListening, setIsListening] = useState(false);
  
  const socketRef = useRef<WebSocket | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const secondaryTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const silenceTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const vadIntervalRef = useRef<number | null>(null);
  const speechDetectedRef = useRef<boolean>(false); // Use ref to track speech state
  const reconnectAttempts = useRef<number>(0);
  const maxReconnectAttempts = 3;
  const reconnectInterval = 7000;

  const SILENCE_DURATION = 2000; // 2 seconds of silence
  const SPEECH_THRESHOLD = 0.01; // Amplitude threshold (0-1 scale)
  const VAD_CHECK_INTERVAL = 100; // Check every 100ms

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
      console.log(`✅ Voice WebSocket connected for session: ${sessionId}`);
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
        console.log('📨 WebSocket message received:', data.type || data.role);
        
        if (data.type === 'pong') {
          console.log('🏓 Received pong, Voice WebSocket alive');
          return;
        }
        if (data.error) {
          console.error('❌ WebSocket error:', data.error);
          setError(`WebSocket error: ${data.error}`);
          setIsProcessing(false);
          if (secondaryTimeoutRef.current) {
            clearTimeout(secondaryTimeoutRef.current);
            secondaryTimeoutRef.current = null;
          }
          return;
        }
        if (data.audio_base64 && data.role === 'assistant') {
          console.log('🎵 Received audio response from backend');
          if (audioRef.current) {
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
              console.log('🔊 Playing assistant response');
            } catch (err) {
              console.error('Error playing audio:', err);
              setError('Failed to play assistant response.');
            }
          }
          setIsProcessing(false);
        }
      } catch (err) {
        console.error('Error processing WebSocket message:', err);
        setError('Failed to process incoming voice message.');
      }
    };

    socketRef.current.onerror = (err) => {
      console.error('❌ Voice WebSocket error:', err);
      setError('WebSocket connection error. Attempting to reconnect...');
    };

    socketRef.current.onclose = (event) => {
      console.log(`🔌 Voice WebSocket closed for session: ${sessionId}`, event);
      if (event.code === 1008) {
        setError(`Session invalid or expired: ${event.reason}`);
      } else if (reconnectAttempts.current < maxReconnectAttempts) {
        reconnectAttempts.current += 1;
        setTimeout(connectWebSocket, reconnectInterval);
      } else {
        setError('Failed to reconnect to voice WebSocket after multiple attempts.');
      }
    };
  }, [sessionId]);

  // Improved Voice Activity Detection using time-domain analysis
  const checkVoiceActivity = useCallback(() => {
    if (!analyserRef.current || !isListening) return false;

    const bufferLength = analyserRef.current.fftSize;
    const dataArray = new Float32Array(bufferLength);
    analyserRef.current.getFloatTimeDomainData(dataArray);

    // Calculate RMS (Root Mean Square) for volume
    let sum = 0;
    for (let i = 0; i < bufferLength; i++) {
      sum += dataArray[i] * dataArray[i];
    }
    const rms = Math.sqrt(sum / bufferLength);

    // Check if speech is detected
    const isSpeaking = rms > SPEECH_THRESHOLD;

    if (isSpeaking) {
      // Speech detected
      if (!speechDetectedRef.current) {
        console.log('🎤 Speech started! RMS:', rms.toFixed(4));
        speechDetectedRef.current = true;
        setIsSpeechDetected(true);
      }

      // Reset silence timeout every time speech is detected
      if (silenceTimeoutRef.current) {
        clearTimeout(silenceTimeoutRef.current);
      }

      // Start new silence timeout
      silenceTimeoutRef.current = setTimeout(() => {
        console.log('⏸️ 3 seconds of silence detected, processing query...');
        processRecording();
      }, SILENCE_DURATION);
    }

    return isSpeaking;
  }, [isListening]);

  // Continuous VAD monitoring
  useEffect(() => {
    if (isListening && !isProcessing && !isPlaying) {
      vadIntervalRef.current = window.setInterval(() => {
        checkVoiceActivity();
      }, VAD_CHECK_INTERVAL);

      return () => {
        if (vadIntervalRef.current) {
          clearInterval(vadIntervalRef.current);
          vadIntervalRef.current = null;
        }
      };
    }
  }, [isListening, isProcessing, isPlaying, checkVoiceActivity]);

  const processRecording = async () => {
    if (!mediaRecorderRef.current || mediaRecorderRef.current.state === 'inactive') {
      console.log('⚠️ Recorder already inactive');
      return;
    }
    
    console.log('📝 Processing recording... Speech was detected:', speechDetectedRef.current);
    
    // Stop the current recording session
    mediaRecorderRef.current.stop();
    setIsListening(false);
    
    // Clear VAD interval
    if (vadIntervalRef.current) {
      clearInterval(vadIntervalRef.current);
      vadIntervalRef.current = null;
    }

    if (silenceTimeoutRef.current) {
      clearTimeout(silenceTimeoutRef.current);
      silenceTimeoutRef.current = null;
    }
  };

  const startContinuousListening = async () => {
    try {
      console.log('🎧 Starting continuous listening...');
      
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        } 
      });
      streamRef.current = stream;

      // Setup audio context for voice detection
      audioContextRef.current = new (window.AudioContext || (window as any).webkitAudioContext)();
      const source = audioContextRef.current.createMediaStreamSource(stream);
      analyserRef.current = audioContextRef.current.createAnalyser();
      analyserRef.current.fftSize = 2048;
      analyserRef.current.smoothingTimeConstant = 0.8;
      source.connect(analyserRef.current);

      // Setup media recorder
      const mimeType = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/mp4';
      mediaRecorderRef.current = new MediaRecorder(stream, { mimeType });
      audioChunksRef.current = [];

      mediaRecorderRef.current.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorderRef.current.onstop = async () => {
        const hadSpeech = speechDetectedRef.current;
        console.log('🛑 Recorder stopped. Chunks:', audioChunksRef.current.length, 'Speech detected:', hadSpeech);
        
        if (audioChunksRef.current.length === 0 || !hadSpeech) {
          console.log('⚠️ No valid speech detected, restarting listening...');
          audioChunksRef.current = [];
          speechDetectedRef.current = false;
          setIsSpeechDetected(false);
          if (!isProcessing && !isPlaying) {
            setTimeout(() => startContinuousListening(), 500);
          }
          return;
        }

        setQueryCount(prev => {
          const newCount = prev + 1;
          console.log(`📨 Processing user query #${newCount}`);
          return newCount;
        });

        setIsProcessing(true);
        const audioBlob = new Blob(audioChunksRef.current, { type: mimeType });
        console.log('📦 Audio blob size:', audioBlob.size, 'bytes');
        
        const arrayBuffer = await audioBlob.arrayBuffer();
        const base64Audio = btoa(
          new Uint8Array(arrayBuffer).reduce(
            (data, byte) => data + String.fromCharCode(byte),
            ''
          )
        );

        console.log('📤 Sending audio to backend. Base64 length:', base64Audio.length);

        if (socketRef.current?.readyState === WebSocket.OPEN) {
          const payload = {
            type: 'audio',
            audio_data: base64Audio,
            timestamp: Date.now() / 1000,
            query_count: queryCount + 1
          };
          
          console.log('📡 Sending WebSocket message:', { 
            type: payload.type, 
            audioLength: payload.audio_data.length,
            timestamp: payload.timestamp 
          });
          
          socketRef.current.send(JSON.stringify(payload));

          playPreliminaryResponse();

          setTimeout(() => {
            if (isProcessing) {
              console.error('⏱️ Timeout: No response from server after 15 seconds');
              setError('No response from server. Please try again.');
              setIsProcessing(false);
              startContinuousListening();
            }
          }, 15000);
        } else {
          console.error('❌ WebSocket is not connected. State:', socketRef.current?.readyState);
          setError('WebSocket is not connected. Please try again.');
          setIsProcessing(false);
          startContinuousListening();
        }

        audioChunksRef.current = [];
        speechDetectedRef.current = false;
        setIsSpeechDetected(false);
      };

      mediaRecorderRef.current.start(100); // Collect data every 100ms
      setIsRecording(true);
      setIsListening(true);
      speechDetectedRef.current = false;
      setIsSpeechDetected(false);
      
      console.log('✅ Listening started successfully');

    } catch (err: any) {
      console.error('❌ Error starting recording:', err);
      setError('Failed to access microphone. Please check permissions.');
    }
  };

  const stopContinuousListening = () => {
    console.log('🔇 Stopping continuous listening...');
    
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
    }
    if (silenceTimeoutRef.current) {
      clearTimeout(silenceTimeoutRef.current);
      silenceTimeoutRef.current = null;
    }
    if (vadIntervalRef.current) {
      clearInterval(vadIntervalRef.current);
      vadIntervalRef.current = null;
    }
    setIsRecording(false);
    setIsListening(false);
    speechDetectedRef.current = false;
    setIsSpeechDetected(false);
  };

  useEffect(() => {
    const queryParams = new URLSearchParams(location.search);
    const sessionIdParam = queryParams.get('sessionId');
    const token = queryParams.get('token');
    
    if (!sessionIdParam || !token) {
      setError('Missing session ID or token. Please access via the chat page.');
      return;
    }
    
    console.log('🔑 Session ID:', sessionIdParam);
    setSessionId(sessionIdParam);

    return () => {
      stopContinuousListening();
      socketRef.current?.close();
      if (secondaryTimeoutRef.current) {
        clearTimeout(secondaryTimeoutRef.current);
      }
      if (audioContextRef.current) {
        audioContextRef.current.close();
      }
    };
  }, [location.search]);

  // Separate effect for WebSocket connection and initialization after sessionId is set
  useEffect(() => {
    if (!sessionId) return;

    const queryParams = new URLSearchParams(location.search);
    const token = queryParams.get('token');
    
    if (!token) return;

    const validateToken = async () => {
      try {
        await axios.get('http://localhost:8000/validate-token/', { params: { token } });
        console.log('✅ Token validated successfully');
        // Connect WebSocket after validation
        connectWebSocket();
        // Auto-start listening after WebSocket connection
        setTimeout(() => {
          startContinuousListening();
        }, 1500);
      } catch (err: any) {
        console.error('❌ Token validation error:', err);
        setError('Invalid or expired token. Please request a new link.');
      }
    };
    
    validateToken();
  }, [sessionId, connectWebSocket]);

  const playPreliminaryResponse = () => {
    if (audioRef.current) {
      const audioPath = getNextPreliminaryAudio();
      console.log(`🔊 Playing preliminary audio ${queryCount + 1}: ${audioPath}`);
      audioRef.current.src = audioPath;
      setCurrentAudioType('preliminary');
      audioRef.current.play()
        .then(() => {
          setIsPlaying(true);
          setIsPaused(false);
        })
        .catch(err => {
          console.error('❌ Error playing preliminary response:', err);
          setError(`Failed to play preliminary audio: ${audioPath}`);
        });
    }
  };

  const playDelayResponse = () => {
    if (audioRef.current) {
      console.log('🔊 Playing delay response');
      audioRef.current.src = '/static/preliminary_response_1.mp3';
      setCurrentAudioType('delay');
      audioRef.current.play()
        .then(() => {
          setIsPlaying(true);
          setIsPaused(false);
        })
        .catch(err => {
          console.error('❌ Error playing delay response:', err);
        });
    }
  };

  const stopResponse = () => {
    console.log('⏹️ Stopping response playback');
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
    // Restart listening after stopping response
    if (!isListening) {
      startContinuousListening();
    }
  };

  const togglePause = () => {
    if (audioRef.current) {
      if (isPaused) {
        console.log('▶️ Resuming playback');
        audioRef.current.play();
        setIsPlaying(true);
        setIsPaused(false);
      } else if (isPlaying) {
        console.log('⏸️ Pausing playback');
        audioRef.current.pause();
        setIsPlaying(false);
        setIsPaused(true);
      }
    }
  };

  const handleAudioEnded = () => {
    console.log('🏁 Audio playback ended. Type:', currentAudioType);
    setIsPlaying(false);
    setIsPaused(false);
    
    if (isProcessing) {
      if (currentAudioType === 'preliminary') {
        secondaryTimeoutRef.current = setTimeout(() => {
          if (isProcessing) {
            playDelayResponse();
          }
        }, 4000);
      }
    } else {
      // Response completed, restart listening
      setCurrentAudioType('none');
      if (!isListening) {
        console.log('🔄 Restarting listening after response...');
        setTimeout(() => {
          startContinuousListening();
        }, 500);
      }
    }
  };

  const handleBack = () => {
    stopContinuousListening();
    const token = new URLSearchParams(location.search).get('token');
    navigate(`/candidate-chat?token=${token}`);
  };

  const getStatusText = () => {
    if (isSpeechDetected) return '🎤 Listening to your query...';
    if (isListening) return '👂 Waiting for you to speak...';
    if (isProcessing) return '🤔 Thinking...';
    if (isPlaying) return '🗣️ Speaking...';
    if (isPaused) return '⏸️ Paused';
    return 'Speak your question, and I\'ll respond with voice.';
  };

  const getBlobClass = () => {
    if (isSpeechDetected) return 'blob listening active';
    if (isListening) return 'blob listening';
    if (isProcessing) return 'blob thinking';
    if (isPlaying) return 'blob speaking';
    return 'blob idle';
  };

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
        <h1 className="text-xl font-bold">Voice Interaction (Hands-free)</h1>
      </div>
      
      <div className="flex-1 flex flex-col items-center justify-center p-4">
        <div className={getBlobClass()}></div>
        <div className="mt-4 text-gray-400 text-center text-lg">
          {getStatusText()}
        </div>
        {isListening && (
          <div className="mt-2 text-sm text-green-500">
            ● Hands-free mode active
          </div>
        )}
        {isSpeechDetected && (
          <div className="mt-2 text-xs text-blue-400">
          </div>
        )}
      </div>
      
      <div className="p-4 flex justify-center items-center space-x-4 bg-black">
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
          console.error('❌ Audio playback error:', e);
          setError('Failed to play audio file');
          setIsPlaying(false);
        }}
      />
    </div>
  );
};

export default VoiceInteraction;