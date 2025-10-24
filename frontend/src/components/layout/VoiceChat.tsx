import { useState, useEffect, useRef } from "react"
import { useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { toast } from "@/components/ui/sonner"
import { Mic, StopCircle, Loader2, Sparkles } from "lucide-react"
import { motion, AnimatePresence } from "framer-motion"

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  timestamp: Date
  audio_base64?: string
}

function VoiceChat() {
  const [searchParams] = useSearchParams()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [isRecording, setIsRecording] = useState(false)
  const [liveTranscript, setLiveTranscript] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [websocket, setWebsocket] = useState<WebSocket | null>(null)
  const [audioContext, setAudioContext] = useState<AudioContext | null>(null)
  const [processor, setProcessor] = useState<ScriptProcessorNode | null>(null)
  const [stream, setStream] = useState<MediaStream | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const token = searchParams.get("token")
    if (token) {
      fetch(`http://localhost:8000/validate-token/?token=${token}`)
        .then(response => {
          if (!response.ok) throw new Error("Invalid token")
          return response.json()
        })
        .then(data => setSessionId(data.session_id))
        .catch(error => {
          console.error("Token validation error:", error)
          toast.error("Invalid or expired link", { duration: 10000 })
        })
    }
  }, [searchParams])

  useEffect(() => {
    if (sessionId) {
      const ws = new WebSocket(`ws://localhost:8000/ws/${sessionId}`)
      setWebsocket(ws)

      ws.onopen = () => {
        console.log("WebSocket connected for voice session:", sessionId)
        ws.send(JSON.stringify({ type: "ping" }))
      }

      ws.onmessage = async (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === "pong") return

          const newMessage: Message = {
            id: crypto.randomUUID(),
            role: data.role,
            content: data.content,
            timestamp: new Date(data.timestamp * 1000),
            audio_base64: data.audio_base64
          }
          setMessages(prev => [...prev, newMessage])
          
          if (data.audio_base64) {
            const audio = new Audio(`data:audio/mp3;base64,${data.audio_base64}`)
            audio.play().catch(() => toast.error("Audio playback failed.", { duration: 10000 }))
          }
        } catch (error) {
          console.error("Error parsing WebSocket message:", error)
          toast.error("Failed to process incoming message", { duration: 5000 })
        }
      }

      ws.onclose = () => {
        toast.warning("WebSocket connection closed", { duration: 10000 })
      }

      ws.onerror = (error) => {
        console.error("WebSocket error:", error)
        toast.error("WebSocket connection error", { duration: 10000 })
      }

      const pingInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping" }))
        }
      }, 30000)

      return () => {
        ws.close()
        clearInterval(pingInterval)
        setWebsocket(null)
      }
    }
  }, [sessionId])

  useEffect(() => {
    return () => {
      if (websocket) websocket.close()
      if (processor) processor.disconnect()
      if (audioContext) audioContext.close()
      if (stream) stream.getTracks().forEach(track => track.stop())
    }
  }, [websocket, processor, audioContext, stream])

  // Audio visualization effect
  useEffect(() => {
    if (isRecording && canvasRef.current && audioContext && stream) {
      const canvas = canvasRef.current
      const ctx = canvas.getContext("2d")
      if (!ctx) return

      const analyser = audioContext.createAnalyser()
      analyser.fftSize = 2048
      const source = audioContext.createMediaStreamSource(stream)
      source.connect(analyser)
      
      const bufferLength = analyser.frequencyBinCount
      const dataArray = new Uint8Array(bufferLength)

      const draw = () => {
        if (!isRecording) return
        requestAnimationFrame(draw)
        analyser.getByteFrequencyData(dataArray)
        
        ctx.fillStyle = "rgb(15, 23, 42)"
        ctx.fillRect(0, 0, canvas.width, canvas.height)
        
        const barWidth = (canvas.width / bufferLength) * 2.5
        let x = 0

        for (let i = 0; i < bufferLength; i++) {
          const barHeight = (dataArray[i] / 255) * canvas.height
          ctx.fillStyle = `rgb(${barHeight + 100}, 156, 255)`
          ctx.fillRect(x, canvas.height - barHeight, barWidth, barHeight)
          x += barWidth + 1
        }
      }

      draw()
    }
  }, [isRecording, audioContext, stream])

  const startRecording = async () => {
    if (!sessionId) {
      toast.error("No session selected", { duration: 10000 })
      return
    }
    setIsRecording(true)
    setLiveTranscript("")
    try {
      const ws = new WebSocket(`ws://localhost:8000/transcribe/${sessionId}`)
      setWebsocket(ws)

      ws.onmessage = (event) => {
        const transcript = event.data
        setLiveTranscript(prev => prev + (prev ? " " : "") + transcript)
      }

      ws.onopen = async () => {
        try {
          const mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: {
              sampleRate: 16000,
              sampleSize: 16,
              channelCount: 1,
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true
            }
          })
          setStream(mediaStream)
          const ctx = new AudioContext({ sampleRate: 16000 })
          setAudioContext(ctx)
          const source = ctx.createMediaStreamSource(mediaStream)
          const proc = ctx.createScriptProcessor(4096, 1, 1)
          setProcessor(proc)

          source.connect(proc)
          proc.connect(ctx.destination)

          proc.onaudioprocess = (e) => {
            if (ws.readyState !== WebSocket.OPEN) {
              ws.close()
              return
            }
            const inputData = e.inputBuffer.getChannelData(0)
            const pcm16 = convertFloat32ToInt16(inputData)
            ws.send(pcm16)
          }
          toast.info("Recording started...", { duration: 5000 })
        } catch (err) {
          console.error("Recording setup error:", err)
          toast.error(`Recording error: ${err instanceof Error ? err.message : String(err)}`, { duration: 10000 })
          setIsRecording(false)
          ws.close()
        }
      }

      ws.onerror = () => {
        toast.error("WebSocket connection failed", { duration: 10000 })
        setIsRecording(false)
        ws.close()
      }

      ws.onclose = (event) => {
        setIsRecording(false)
        if (processor) processor.disconnect()
        if (audioContext) audioContext.close()
        if (stream) stream.getTracks().forEach(track => track.stop())
        setWebsocket(null)
        setProcessor(null)
        setAudioContext(null)
        setStream(null)
        if (liveTranscript.trim()) {
          handleSubmit(liveTranscript)
        }
      }
    } catch (err) {
      console.error("WebSocket setup error:", err)
      toast.error(`Recording error: ${err instanceof Error ? err.message : String(err)}`, { duration: 10000 })
      setIsRecording(false)
    }
  }

  const stopRecording = async () => {
    if (websocket && isRecording) {
      websocket.close(1000, "Recording stopped by user")
      setIsRecording(false)
      toast.info("Recording stopped, processing transcription...", { duration: 5000 })
    }
  }

  const convertFloat32ToInt16 = (buffer: Float32Array): ArrayBuffer => {
    const l = buffer.length
    const result = new Int16Array(l)
    for (let i = 0; i < l; i++) {
      result[i] = buffer[i] * 0x7fff
    }
    return result.buffer
  }

  const handleSubmit = async (transcript: string) => {
    if (!sessionId || !transcript.trim()) return
    setIsLoading(true)

    try {
      const response = await fetch(`http://localhost:8000/chat/${sessionId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: transcript, voice_mode: true, role: "candidate" })
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || "Failed to send message")
      }
      setLiveTranscript("")
    } catch (error) {
      console.error("Error sending message:", error)
      toast.error(`Failed to process request: ${error instanceof Error ? error.message : String(error)}`, { duration: 10000 })
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex h-screen w-full flex-col bg-gradient-to-br from-slate-900 to-slate-800 text-white">
      <header className="p-4 border-b border-slate-700">
        <h1 className="text-2xl font-bold text-center">Voice Chat</h1>
      </header>
      
      <div className="flex-1 flex flex-col items-center justify-center p-6">
        <AnimatePresence>
          {isRecording ? (
            <motion.div
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.8, opacity: 0 }}
              className="text-center space-y-6"
            >
              <canvas 
                ref={canvasRef} 
                width={400} 
                height={100} 
                className="rounded-lg bg-slate-950 shadow-lg"
              />
              <div className="text-lg font-medium min-h-[24px]">
                {liveTranscript || "Listening..."}
              </div>
              <Button
                variant="destructive"
                size="lg"
                className="rounded-full h-16 w-16"
                onClick={stopRecording}
                disabled={isLoading}
              >
                <StopCircle className="h-8 w-8" />
              </Button>
            </motion.div>
          ) : (
            <motion.div
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.8, opacity: 0 }}
              className="text-center space-y-6"
            >
              <div className="w-24 h-24 bg-gradient-to-r from-blue-500 to-purple-600 rounded-full flex items-center justify-center mx-auto">
                <Sparkles className="h-12 w-12 text-white" />
              </div>
              <h2 className="text-xl font-semibold">Start a Voice Conversation</h2>
              <p className="text-slate-300">Click the button below to begin speaking</p>
              <Button
                variant="default"
                size="lg"
                className="rounded-full h-16 w-16 bg-gradient-to-r from-blue-500 to-purple-600 hover:from-blue-600 hover:to-purple-700"
                onClick={startRecording}
                disabled={isLoading}
              >
                {isLoading ? (
                  <Loader2 className="h-8 w-8 animate-spin" />
                ) : (
                  <Mic className="h-8 w-8" />
                )}
              </Button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}

export default VoiceChat