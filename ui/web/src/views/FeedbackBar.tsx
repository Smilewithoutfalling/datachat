// 👍👎（phase5-frontend.md §2.5）：PUT /messages/{id}/feedback {rating: up|down|null, note}。再点一次同一个取消评价（null）。
import { useState } from "react";
import { type Client, errText } from "../client";
import type { Feedback, Rating } from "../types";
import { IconThumbDown, IconThumbUp } from "./icons";

export function FeedbackBar({ c, messageId, initial }: { c: Client; messageId: string; initial: Feedback | null | undefined }) {
  const [rating, setRating] = useState<Rating>(initial?.rating ?? null);
  const [note, setNote] = useState(initial?.note ?? "");
  const [saved, setSaved] = useState(initial?.note ?? "");
  const [err, setErr] = useState("");
  const send = (r: Rating, n: string) =>
    c.feedback(messageId, r, n).then(
      (out) => (setRating(out.rating), setNote(out.note), setSaved(out.note), setErr("")),
      (e) => setErr(errText(e)),
    );
  return (
    <div className="feedback" role="group" aria-label="评价这条回答">
      <button type="button" aria-pressed={rating === "up"} aria-label="有用" onClick={() => send(rating === "up" ? null : "up", note)}>
        <IconThumbUp size={14} />
      </button>
      <button type="button" aria-pressed={rating === "down"} aria-label="没用" onClick={() => send(rating === "down" ? null : "down", note)}>
        <IconThumbDown size={14} />
      </button>
      {rating ? (
        <>
          <input
            aria-label="补充说明"
            placeholder="补充说明（可选）"
            maxLength={1000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <button type="button" className="save" disabled={note === saved} onClick={() => send(rating, note)}>
            保存说明
          </button>
        </>
      ) : null}
      {err ? <span role="alert" className="err small">{err}</span> : null}
    </div>
  );
}
