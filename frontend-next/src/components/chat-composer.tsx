import { useRef, useState } from "react";
import {
  AtSign,
  ArrowUp,
  ScanSearch,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandInput,
  CommandList,
  CommandEmpty,
  CommandGroup,
  CommandItem,
} from "@/components/ui/command";
import { usePreferences } from "@/state/preferences";
import type { ChatParticipant } from "@/domain/chat";
const participants = [
  {
    id: "suhail",
    name: "Suhail",
    description: "General case context",
    arabic: "السياق العام للحالة",
    icon: Sparkles,
  },
  {
    id: "investigator",
    name: "Investigator",
    description: "Evidence and diagnosis",
    arabic: "الأدلة والتشخيص",
    icon: ScanSearch,
  },
  {
    id: "reviewer",
    name: "Reviewer",
    description: "Uncertainty and approval",
    arabic: "الشكوك والتفويض",
    icon: ShieldCheck,
  },
] as const;
export function ChatComposer({
  value,
  onChange,
  onSend,
  disabled,
  label,
  placeholder,
  pageHelper = false,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: (value: string) => void;
  disabled: boolean;
  label: string;
  placeholder: string;
  pageHelper?: boolean;
}) {
  const { t } = usePreferences();
  const [mentionOpen, setMentionOpen] = useState(false);
  const [query, setQuery] = useState("");
  const fromTyping = useRef(false);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const commandRef = useRef<HTMLInputElement>(null);
  function mention(id: ChatParticipant) {
    onChange(
      /(?:^|\s)@\w*$/.test(value)
        ? value.replace(/@\w*$/, `@${id} `)
        : `${value}${value && !value.endsWith(" ") ? " " : ""}@${id} `,
    );
    setMentionOpen(false);
    textRef.current?.focus();
  }
  return (
    <form
      className="conversation-composer"
      onSubmit={(e) => {
        e.preventDefault();
        onSend(value);
      }}
    >
      <Textarea
        ref={textRef}
        aria-label={label}
        placeholder={placeholder}
        value={value}
        disabled={disabled}
        onChange={(e) => {
          onChange(e.target.value);
          const match = e.target.value.match(/(?:^|\s)@(\w*)$/);
          fromTyping.current = !!match;
          setMentionOpen(!!match);
          setQuery(match?.[1] ?? "");
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" && mentionOpen) {
            e.preventDefault();
            commandRef.current?.focus();
          } else if (e.key === "Escape" && mentionOpen) {
            e.preventDefault();
            setMentionOpen(false);
          } else if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (mentionOpen) commandRef.current?.focus();
            else onSend(value);
          }
        }}
        rows={2}
      />
      <div className="composer-actions">
        <Popover open={mentionOpen} onOpenChange={setMentionOpen}>
          <PopoverTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={t("Mention an assistant", "الإشارة إلى مساعد")}
              disabled={disabled}
              onClick={() => {
                fromTyping.current = false;
                setQuery("");
              }}
            >
              <AtSign size={14} />
            </Button>
          </PopoverTrigger>
          <PopoverContent
            side="top"
            align="start"
            className="mention-popover"
            onOpenAutoFocus={(e) => {
              if (fromTyping.current) e.preventDefault();
            }}
          >
            <Command>
              <CommandInput
                ref={commandRef}
                aria-label={t(
                  "Find assistant mention",
                  "البحث عن مساعد للإشارة إليه",
                )}
                placeholder={t("Choose an assistant…", "اختر مساعداً…")}
                value={query}
                onValueChange={setQuery}
              />
              <CommandList>
                <CommandEmpty>
                  {t("No matching assistant.", "لا يوجد مساعد مطابق.")}
                </CommandEmpty>
                <CommandGroup
                  heading={t("SIMULATED PARTICIPANTS", "مساعدو المحاكاة")}
                >
                  {participants
                    .filter((p) => !pageHelper || p.id === "suhail")
                    .map((p) => (
                      <CommandItem
                        key={p.id}
                        value={`${p.id} ${p.name}`}
                        onSelect={() => mention(p.id)}
                      >
                        <p.icon size={14} />
                        <div>
                          <b>@{p.id}</b>
                          <small>
                            {pageHelper
                              ? t(
                                  "Page filters and views",
                                  "تصفية الصفحة والعرض",
                                )
                              : t(p.description, p.arabic)}
                          </small>
                        </div>
                      </CommandItem>
                    ))}
                </CommandGroup>
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
        <span>
          {t(
            "Enter to send · Shift + Enter for a new line",
            "إدخال للإرسال · Shift + Enter لسطر جديد",
          )}
        </span>
        <Button
          type="submit"
          size="icon-sm"
          disabled={!value.trim() || disabled}
          aria-label={
            pageHelper
              ? t("Apply assistant request", "تطبيق طلب المساعد")
              : t("Send question", "إرسال السؤال")
          }
        >
          <ArrowUp size={14} />
        </Button>
      </div>
    </form>
  );
}
