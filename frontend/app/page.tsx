"use client";

import { useState, useEffect } from "react";
import { Sidebar } from "../components/sidebar/Sidebar";
import { ChatWorkspace } from "../components/workspace/ChatWorkspace";
import { Conversation, Message, QueryDataRow, ChartConfig } from "../types/chat";

const formatCurrentTime = (): string => {
  const now = new Date();
  let hours = now.getHours();
  const minutes = now.getMinutes().toString().padStart(2, "0");
  const ampm = hours >= 12 ? "PM" : "AM";
  hours = hours % 12;
  hours = hours ? hours : 12;
  return `${hours}:${minutes} ${ampm}`;
};

const INITIAL_CONVERSATIONS: Conversation[] = [
  {
    id: "conv-1",
    title: "New Conversation",
    timestamp: formatCurrentTime(),
    messages: [],
  },
];

interface ApiConversation {
  id: string;
  title: string;
  updated_at?: string;
}

interface ApiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp?: string;
  sql?: string;
  data?: QueryDataRow[];
  metrics?: Record<string, unknown>;
  chart_config?: ChartConfig | null;
  thought_trace?: string[];
}

function getBackendUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_API_URL || process.env.NEXT_PUBLIC_BACKEND_URL;
  if (envUrl && envUrl.trim() !== "") {
    return envUrl.trim().replace(/\/+$/, "");
  }
  // Default to localhost:8000 when developing locally in the browser
  if (
    typeof window !== "undefined" &&
    (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1")
  ) {
    return "http://localhost:8000";
  }
  // In production (e.g. Vercel) if envUrl wasn't set, warn in console
  if (typeof window !== "undefined") {
    console.warn(
      "[DataPilot] NEXT_PUBLIC_API_URL is not set. Please configure your Render backend URL in your Vercel project environment variables."
    );
  }
  return "";
}

export default function Home() {
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(true);
  const [conversations, setConversations] = useState<Conversation[]>(
    INITIAL_CONVERSATIONS
  );
  const [activeConversationId, setActiveConversationId] = useState<string>(
    INITIAL_CONVERSATIONS[0].id
  );
  const [isLoading, setIsLoading] = useState<boolean>(false);

  const backendUrl = getBackendUrl();

  // Initial load: Fetch persistent conversations from backend Supabase
  useEffect(() => {
    async function loadConversations() {
      try {
        const res = await fetch(`${backendUrl}/api/conversations`);
        if (!res.ok) return;
        const data = await res.json();
        if (data.conversations && data.conversations.length > 0) {
          const loaded: Conversation[] = data.conversations.map((c: ApiConversation) => ({
            id: c.id,
            title: c.title,
            timestamp: c.updated_at ? new Date(c.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : formatCurrentTime(),
            messages: [],
          }));
          setConversations(loaded);
          setActiveConversationId(loaded[0].id);

          // Hydrate the first conversation's messages
          const firstDetailRes = await fetch(`${backendUrl}/api/conversations/${loaded[0].id}`);
          if (firstDetailRes.ok) {
            const firstDetail = await firstDetailRes.json();
            if (firstDetail.messages) {
              setConversations((prev) =>
                prev.map((conv) =>
                  conv.id === loaded[0].id
                    ? {
                        ...conv,
                        messages: firstDetail.messages.map((m: ApiMessage) => ({
                          id: m.id,
                          role: m.role,
                          content: m.content,
                          timestamp: m.timestamp || formatCurrentTime(),
                          sql: m.sql,
                          data: m.data,
                          metrics: m.metrics,
                          chartConfig: m.chart_config,
                          thoughtTrace: m.thought_trace,
                        })),
                      }
                    : conv
                )
              );
            }
          }
        }
      } catch (err) {
        console.warn("Could not load stored conversations from backend:", err);
      }
    }
    loadConversations();
  }, [backendUrl]);

  const activeConversation =
    conversations.find((c) => c.id === activeConversationId) ||
    conversations[0];

  const handleToggleSidebar = () => {
    setIsSidebarOpen((prev) => !prev);
  };

  const handleNewChat = () => {
    const newId = `conv-${Date.now()}`;
    const newConversation: Conversation = {
      id: newId,
      title: "New Conversation",
      timestamp: formatCurrentTime(),
      messages: [],
    };
    setConversations((prev) => [newConversation, ...prev]);
    setActiveConversationId(newId);
  };

  const handleSelectConversation = async (id: string) => {
    setActiveConversationId(id);
    const target = conversations.find((c) => c.id === id);
    if (target && target.messages.length === 0) {
      try {
        const res = await fetch(`${backendUrl}/api/conversations/${id}`);
        if (res.ok) {
          const detail = await res.json();
          if (detail.messages) {
            setConversations((prev) =>
              prev.map((c) =>
                c.id === id
                  ? {
                      ...c,
                      messages: detail.messages.map((m: ApiMessage) => ({
                        id: m.id,
                        role: m.role,
                        content: m.content,
                        timestamp: m.timestamp || formatCurrentTime(),
                        sql: m.sql,
                        data: m.data,
                        metrics: m.metrics,
                        chartConfig: m.chart_config,
                        thoughtTrace: m.thought_trace,
                      })),
                    }
                  : c
              )
            );
          }
        }
      } catch (err) {
        console.warn("Error hydrating conversation messages:", err);
      }
    }
  };

  const handleDeleteConversation = async (id: string) => {
    try {
      await fetch(`${backendUrl}/api/conversations/${id}`, { method: "DELETE" });
    } catch (err) {
      console.warn("Could not delete conversation on backend:", err);
    }

    setConversations((prev) => {
      const filtered = prev.filter((c) => c.id !== id);
      if (filtered.length === 0) {
        const freshId = `conv-${Date.now()}`;
        const freshConv: Conversation = {
          id: freshId,
          title: "New Conversation",
          timestamp: formatCurrentTime(),
          messages: [],
        };
        setActiveConversationId(freshId);
        return [freshConv];
      }
      if (activeConversationId === id) {
        setActiveConversationId(filtered[0].id);
      }
      return filtered;
    });
  };

  const handleSendMessage = async (text: string) => {
    const timeStr = formatCurrentTime();
    const userMessage: Message = {
      id: `msg-${Date.now()}`,
      role: "user",
      content: text,
      timestamp: timeStr,
    };

    const assistantMsgId = `msg-${Date.now() + 1}`;
    const initialAssistantMessage: Message = {
      id: assistantMsgId,
      role: "assistant",
      content: "",
      timestamp: timeStr,
      isStreaming: true,
      steps: ["Analyzing inquiry & schema..."],
    };

    // Update conversation with user message & streaming assistant message
    setConversations((prev) =>
      prev.map((c) => {
        if (c.id === activeConversationId) {
          const isFirstMessage = c.messages.length === 0;
          return {
            ...c,
            title: isFirstMessage ? text : c.title,
            timestamp: timeStr,
            messages: [...c.messages, userMessage, initialAssistantMessage],
          };
        }
        return c;
      })
    );

    setIsLoading(true);

    const backendUrl = getBackendUrl();

    try {
      const response = await fetch(`${backendUrl}/api/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: text,
          conversation_id: activeConversationId,
        }),
      });

      if (response.status === 429) {
        const retryHeader = response.headers.get("Retry-After") || "60";
        throw new Error(`Rate limit exceeded: 30 requests/minute. Please wait ${retryHeader} seconds.`);
      }

      if (!response.ok) {
        throw new Error(`API error: ${response.statusText}`);
      }

      if (!response.body) {
        throw new Error("No readable stream received from backend.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let currentEvent = "";
      let accumulatedText = "";
      const accumulatedSteps: string[] = ["🔍 Analyzing Inquiry & Schema"];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed.startsWith("event:")) {
            currentEvent = trimmed.replace("event:", "").trim();
          } else if (trimmed.startsWith("data:")) {
            const rawData = trimmed.replace("data:", "").trim();
            if (!rawData) continue;

            try {
              const parsed = JSON.parse(rawData);

              if (currentEvent === "step" || parsed.step || parsed.badge) {
                const stepText = parsed.badge || parsed.step || "Processing...";
                if (!accumulatedSteps.includes(stepText)) {
                  accumulatedSteps.push(stepText);
                }

                setConversations((prev) =>
                  prev.map((c) =>
                    c.id === activeConversationId
                      ? {
                          ...c,
                          messages: c.messages.map((m) =>
                            m.id === assistantMsgId
                              ? {
                                  ...m,
                                  steps: [...accumulatedSteps],
                                  sql: parsed.sql || m.sql,
                                }
                              : m
                          ),
                        }
                      : c
                  )
                );
              } else if (currentEvent === "token" || parsed.delta) {
                const delta = parsed.delta || "";
                accumulatedText += delta;

                setConversations((prev) =>
                  prev.map((c) =>
                    c.id === activeConversationId
                      ? {
                          ...c,
                          messages: c.messages.map((m) =>
                            m.id === assistantMsgId
                              ? {
                                  ...m,
                                  content: accumulatedText,
                                }
                              : m
                          ),
                        }
                      : c
                  )
                );
              } else if (currentEvent === "done" || parsed.response !== undefined) {
                setConversations((prev) =>
                  prev.map((c) =>
                    c.id === activeConversationId
                      ? {
                          ...c,
                          messages: c.messages.map((m) =>
                            m.id === assistantMsgId
                              ? {
                                  ...m,
                                  content: parsed.response || accumulatedText,
                                  sql: parsed.sql,
                                  data: parsed.data,
                                  columns: parsed.columns,
                                  rowCount: parsed.row_count,
                                  executionTimeMs: parsed.execution_time_ms,
                                  chartConfig: parsed.chart_config,
                                  thoughtTrace: parsed.thought_trace,
                                  isStreaming: false,
                                }
                              : m
                          ),
                        }
                      : c
                  )
                );
              }
            } catch (err) {
              console.error("Error parsing SSE data line:", err, rawData);
            }
          }
        }
      }
    } catch (error) {
      console.error("Failed to fetch response from backend:", error);

      setConversations((prev) =>
        prev.map((c) =>
          c.id === activeConversationId
            ? {
                ...c,
                messages: c.messages.map((m) =>
                  m.id === assistantMsgId
                    ? {
                        ...m,
                        content:
                          `I encountered an issue connecting to the backend service (${backendUrl || "not configured"}). Please verify that your Render backend is active and that NEXT_PUBLIC_API_URL is configured in your Vercel project environment variables.`,
                        isStreaming: false,
                      }
                    : m
                ),
              }
            : c
        )
      );
    } finally {
      setIsLoading(false);
      // Ensure streaming flag is cleared
      setConversations((prev) =>
        prev.map((c) =>
          c.id === activeConversationId
            ? {
                ...c,
                messages: c.messages.map((m) =>
                  m.id === assistantMsgId
                    ? { ...m, isStreaming: false }
                    : m
                ),
              }
            : c
        )
      );
    }
  };

  return (
    <div className="flex h-screen w-screen bg-[#181A20] text-slate-100 overflow-hidden font-sans antialiased">
      {/* Collapsible Left Sidebar */}
      <Sidebar
        isOpen={isSidebarOpen}
        onToggle={handleToggleSidebar}
        conversations={conversations}
        activeConversationId={activeConversationId}
        onSelectConversation={handleSelectConversation}
        onNewChat={handleNewChat}
        onDeleteConversation={handleDeleteConversation}
        userName="Sohel Islam"
      />

      {/* Main Workspace Area */}
      <ChatWorkspace
        isSidebarOpen={isSidebarOpen}
        onToggleSidebar={handleToggleSidebar}
        messages={activeConversation.messages}
        onSendMessage={handleSendMessage}
        isLoading={isLoading}
        userName="Sohel Islam"
      />
    </div>
  );
}
