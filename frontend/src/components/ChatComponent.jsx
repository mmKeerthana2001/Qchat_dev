import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './ChatComponent.css';

const ChatComponent = ({ sessionId }) => {
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState([]);
  const [error, setError] = useState(null);

  const sendQuery = async () => {
    try {
      const response = await axios.post(`http://localhost:8000/chat/${sessionId}`, {
        query,
        role: 'candidate',
        voice_mode: false,
      });
      const { response: assistantResponse, media_data } = response.data;
      setMessages((prev) => [
        ...prev,
        { role: 'user', content: query },
        { role: 'assistant', content: assistantResponse, media_data },
      ]);
      setQuery('');
      setError(null);
    } catch (err) {
      setError('Error sending query. Please try again.');
      console.error(err);
    }
  };

  return (
    <div className="chat-container">
      <h2>Chat with Quadrant Technologies</h2>
      <div className="messages">
        {messages.map((msg, index) => (
          <div key={index} className={`message ${msg.role}`}>
            <strong>{msg.role === 'user' ? 'You' : 'Assistant'}:</strong> {msg.content}
            {msg.media_data && msg.media_data.type === 'image' && (
              <div className="media">
                <h3>Related Image</h3>
                <img src={msg.media_data.url} alt="Related content" style={{ maxWidth: '100%', height: 'auto' }} />
              </div>
            )}
          </div>
        ))}
      </div>
      {error && <p className="error">{error}</p>}
      <div className="input-container">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask a question..."
        />
        <button onClick={sendQuery}>Send</button>
      </div>
    </div>
  );
};

export default ChatComponent;