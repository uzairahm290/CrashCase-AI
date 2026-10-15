"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, type CarCategory } from "@/lib/api";
import styles from "./new.module.css";

const MAX_FILES = 6;
const MAX_MB = 10;
const CATEGORIES: { value: CarCategory; text: string; hint: string }[] = [
  { value: "hatchback", text: "Hatchback", hint: "Alto, Mehran, Cultus" },
  { value: "sedan", text: "Sedan", hint: "Corolla, Civic, City" },
  { value: "suv", text: "SUV", hint: "Fortuner, Sportage, Tucson" },
];

type Picked = { file: File; url: string };

export default function NewClaimPage() {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [picked, setPicked] = useState<Picked[]>([]);
  const [category, setCategory] = useState<CarCategory>("sedan");
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => () => picked.forEach((p) => URL.revokeObjectURL(p.url)), [picked]);

  function add(files: FileList | File[]) {
    setError(null);
    const incoming = Array.from(files).filter((f) => f.type.startsWith("image/"));
    const tooBig = incoming.find((f) => f.size > MAX_MB * 1024 * 1024);
    if (tooBig) return setError(`${tooBig.name} is over ${MAX_MB} MB. Send a smaller photo.`);
    const room = MAX_FILES - picked.length;
    if (incoming.length > room) setError(`A claim takes up to ${MAX_FILES} photos. Extra photos were left out.`);
    setPicked((p) => [...p, ...incoming.slice(0, room).map((file) => ({ file, url: URL.createObjectURL(file) }))]);
  }

  function remove(i: number) {
    setPicked((p) => p.filter((_, j) => j !== i));
  }

  async function submit() {
    setSending(true);
    setError(null);
    try {
      const claim = await api.createClaim(
        picked.map((p) => p.file),
        category,
      );
      router.push(`/claims/${claim.claim_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The claim could not be sent.");
      setSending(false);
    }
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Start a claim</h1>
          <p className="muted">
            Add photos of the damage and pick the type of car. You get an itemised estimate with the past
            claims it was priced against.
          </p>
        </div>
      </header>

      <div className={styles.grid}>
        <section className={`panel ${styles.photos}`} aria-labelledby="photos-h">
          <div className={styles.sectionHead}>
            <h2 id="photos-h">Photos</h2>
            <span className="muted">
              {picked.length} of {MAX_FILES}
            </span>
          </div>

          <div
            className={styles.drop}
            data-dragging={dragging || undefined}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              add(e.dataTransfer.files);
            }}
          >
            {picked.length === 0 ? (
              <button type="button" className={styles.dropEmpty} onClick={() => input.current?.click()}>
                <svg width="56" height="56" viewBox="0 0 32 32" aria-hidden="true">
                  <path
                    d="M3 11V3h8M21 3h8v8M29 21v8h-8M11 29H3v-8"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  />
                  <path d="M16 10v12M10 16h12" stroke="currentColor" strokeWidth="2" />
                </svg>
                <strong>Drop photos here or choose files</strong>
                <span className="muted">JPG or PNG, up to {MAX_MB} MB each</span>
              </button>
            ) : (
              <ul className={styles.thumbs}>
                {picked.map((p, i) => (
                  <li key={p.url}>
                    <img src={p.url} alt={`Photo ${i + 1}: ${p.file.name}`} />
                    <button type="button" onClick={() => remove(i)} aria-label={`Remove ${p.file.name}`}>
                      Remove
                    </button>
                  </li>
                ))}
                {picked.length < MAX_FILES && (
                  <li>
                    <button type="button" className={styles.addMore} onClick={() => input.current?.click()}>
                      Add photo
                    </button>
                  </li>
                )}
              </ul>
            )}
            <input
              ref={input}
              type="file"
              accept="image/*"
              multiple
              hidden
              onChange={(e) => {
                if (e.target.files) add(e.target.files);
                e.target.value = "";
              }}
            />
          </div>

          <div className={styles.tips}>
            <h3>Photos that price well</h3>
            <ul>
              <li>One wide shot of the damaged side, so the part is clear.</li>
              <li>A close-up of each dent, scratch or crack.</li>
              <li>Daylight or a lit garage. Dark and blurry photos are sent back.</li>
            </ul>
          </div>
        </section>

        <section className={`panel ${styles.side}`} aria-labelledby="car-h">
          <h2 id="car-h">Car</h2>
          <div className={styles.cats} role="radiogroup" aria-label="Type of car">
            {CATEGORIES.map((c) => (
              <label key={c.value} className={styles.cat} data-on={category === c.value || undefined}>
                <input
                  type="radio"
                  name="category"
                  value={c.value}
                  checked={category === c.value}
                  onChange={() => setCategory(c.value)}
                />
                <span className={styles.catName}>{c.text}</span>
                <span className="muted">{c.hint}</span>
              </label>
            ))}
          </div>
          <p className="muted">Parts cost more on bigger cars, so this changes the estimate.</p>

          {error && <p className="error-box">{error}</p>}

          <button className="btn btn-marker" disabled={picked.length === 0 || sending} onClick={submit}>
            {sending ? "Sending photos…" : "Get estimate"}
          </button>
        </section>
      </div>
    </div>
  );
}
