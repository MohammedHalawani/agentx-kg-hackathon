import type { ReactNode } from "react";
import { motion } from "motion/react";
import {
  CheckCheck,
  ShieldCheck,
  ScanSearch,
  Sparkles,
  AlertCircle,
  RotateCcw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { CanopusReplyContent } from "@/components/canopus-reply";
import {
  Message,
  MessageGroup,
  MessageAvatar,
  MessageContent,
  MessageHeader,
  MessageFooter,
} from "@/components/ui/message";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import {
  MessageScrollerProvider,
  MessageScroller,
  MessageScrollerViewport,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerButton,
} from "@/components/ui/message-scroller";
import { Marker, MarkerIcon, MarkerContent } from "@/components/ui/marker";
import { Spinner } from "@/components/ui/spinner";
import { usePreferences } from "@/state/preferences";
import type { ChatEntry } from "@/domain/chat";
import { timeLabel } from "@/lib/dates";
import { useMediaQuery } from "@/hooks/use-media-query";

const MotionItem = motion.create(MessageScrollerItem);
export function ConversationTranscript({
  messages,
  intro,
  activity,
  typing,
  label,
  onRetry,
}: {
  messages: ChatEntry[];
  intro?: ReactNode;
  activity?: ReactNode;
  typing?: string;
  label: string;
  onRetry?: (messageId: string) => void;
}) {
  const { t, preferences } = usePreferences();
  const systemReducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const reduced = preferences.motion === "reduce" || systemReducedMotion;
  const groups: ChatEntry[][] = [];
  for (const message of messages) {
    const last = groups.at(-1),
      previous = last?.at(-1);
    if (
      previous &&
      previous.role === message.role &&
      previous.agent === message.agent &&
      Math.abs(Date.parse(message.timestamp) - Date.parse(previous.timestamp)) <
        300_000
    )
      last!.push(message);
    else groups.push([message]);
  }
  return (
    <MessageScrollerProvider
      autoScroll
      defaultScrollPosition={messages.length ? "last-anchor" : "start"}
      scrollPreviousItemPeek={25}
    >
      <MessageScroller>
        <MessageScrollerViewport aria-label={label} tabIndex={0}>
          <MessageScrollerContent className="conversation-content">
            {activity && (
              <MessageScrollerItem messageId="activity">
                {activity}
              </MessageScrollerItem>
            )}
            {messages.length === 0 && intro && (
              <MessageScrollerItem messageId="welcome">
                {intro}
              </MessageScrollerItem>
            )}
            {groups.map((group) => (
              <MotionItem
                key={group[0].id}
                messageId={group[0].id}
                scrollAnchor={group[0].role === "user"}
                initial={{
                  opacity: 0,
                  y: reduced ? 0 : 3,
                }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: reduced ? 0 : 0.18 }}
              >
                <MessageGroup>
                  {group.map((message, index) => (
                    <ConversationMessage
                      key={message.id}
                      message={message}
                      continuation={index > 0}
                      retryDisabled={!!typing}
                      onRetry={
                        onRetry && message.request
                          ? () => onRetry(message.id)
                          : undefined
                      }
                    />
                  ))}
                </MessageGroup>
              </MotionItem>
            ))}
            {typing && (
              <MessageScrollerItem messageId="processing">
                <Marker role="status" className="conversation-marker">
                  <MarkerIcon>
                    <Spinner className="size-3" />
                  </MarkerIcon>
                  <MarkerContent>{typing}</MarkerContent>
                </Marker>
              </MessageScrollerItem>
            )}
          </MessageScrollerContent>
        </MessageScrollerViewport>
        <MessageScrollerButton
          aria-label={t("Jump to latest", "الانتقال إلى أحدث رسالة")}
          title={t("Jump to latest", "الانتقال إلى أحدث رسالة")}
          behavior={reduced ? "instant" : "smooth"}
        />
      </MessageScroller>
    </MessageScrollerProvider>
  );
}
function ConversationMessage({
  message,
  onRetry,
  retryDisabled,
  continuation = false,
}: {
  message: ChatEntry;
  onRetry?: () => void;
  retryDisabled?: boolean;
  continuation?: boolean;
}) {
  const { t } = usePreferences();
  const user = message.role === "user";
  const agent = message.agent ?? "suhail";
  const Icon =
    agent === "reviewer"
      ? ShieldCheck
      : agent === "investigator"
        ? ScanSearch
        : Sparkles;
  return (
    <Message
      align={user ? "end" : "start"}
      data-entry-id={message.id}
      data-continuation={continuation}
    >
      {!user && (
        <MessageAvatar
          className={`conversation-avatar ${continuation ? "invisible" : ""}`}
        >
          <Avatar size="sm">
            <AvatarFallback
              className={`participant-avatar participant-${agent}`}
            >
              <Icon size={12} />
            </AvatarFallback>
          </Avatar>
        </MessageAvatar>
      )}
      <MessageContent className="conversation-message-content">
        {!continuation && (
          <MessageHeader className="conversation-sender">
            {user
              ? t("You", "أنت")
              : {
                  suhail: t("Canopus", "كانوبس"),
                  investigator: t("Investigator", "المحقق"),
                  reviewer: t("Reviewer", "المراجع"),
                }[agent]}
            <time dateTime={message.timestamp}>
              {timeLabel(message.timestamp)}
            </time>
          </MessageHeader>
        )}
        <Bubble
          variant={user ? "tinted" : "ghost"}
          align={user ? "end" : "start"}
          className="conversation-bubble"
        >
          <BubbleContent className="text-xs leading-relaxed">
            {message.text && (
              <p dir="auto">
                {message.text}
                <span
                  className={message.streaming ? "stream-cursor" : "hidden"}
                  aria-hidden="true"
                />
              </p>
            )}
            {message.reply && <CanopusReplyContent reply={message.reply} />}
            {message.error && (
              <div className="canopus-response-error" role="alert">
                <AlertCircle size={14} />
                <p>{message.error}</p>
                {onRetry && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={onRetry}
                    disabled={retryDisabled}
                  >
                    <RotateCcw size={12} />
                    {t("Retry response", "إعادة المحاولة")}
                  </Button>
                )}
              </div>
            )}
          </BubbleContent>
        </Bubble>
        {!user && !message.streaming && !message.error && (
          <MessageFooter className="conversation-message-meta">
            {t("Simulated response", "إجابة محاكاة")}
            {message.actions && message.actions.length > 0 && (
              <span>
                <CheckCheck size={10} />
                {t("Page updated", "تم تحديث الصفحة")}
              </span>
            )}
          </MessageFooter>
        )}
      </MessageContent>
    </Message>
  );
}
