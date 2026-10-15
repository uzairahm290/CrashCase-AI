"use client";

import { useState } from "react";
import { api, type Assessment, type QualityResult } from "@/lib/api";
import { label } from "@/lib/format";
import styles from "./PhotoStage.module.css";

type Props = {
  claimId: string;
  images: string[];
  assessments: Assessment[];
  quality: QualityResult[];
  current: string;
  onPick: (image: string) => void;
  selected: number | null;
  onSelect: (n: number | null) => void;
};

/** The light box: one photo large, damage outlined and numbered to match the job card. */
export default function PhotoStage({ claimId, images, assessments, quality, current, onPick, selected, onSelect }: Props) {
  const [size, setSize] = useState<Record<string, { w: number; h: number }>>({});
  const dims = size[current];
  const q = quality.find((x) => x.image === current);

  return (
    <div className={styles.stage}>
      <div className={styles.frame}>
        <div className={styles.photo}>
          <img
            src={api.imageUrl(claimId, current)}
            alt={`Claim photo ${images.indexOf(current) + 1}`}
            onLoad={(e) => {
              const img = e.currentTarget;
              setSize((s) => ({ ...s, [current]: { w: img.naturalWidth, h: img.naturalHeight } }));
            }}
          />
          {dims &&
            assessments.map((a, i) => {
              if (a.image !== current) return null;
              const [x1, y1, x2, y2] = a.detection.bbox;
              return (
                <button
                  key={i}
                  type="button"
                  className={styles.box}
                  data-on={selected === i || undefined}
                  data-dim={selected != null && selected !== i ? true : undefined}
                  style={{
                    left: `${(x1 / dims.w) * 100}%`,
                    top: `${(y1 / dims.h) * 100}%`,
                    width: `${((x2 - x1) / dims.w) * 100}%`,
                    height: `${((y2 - y1) / dims.h) * 100}%`,
                  }}
                  onClick={() => onSelect(selected === i ? null : i)}
                  aria-label={`Damage ${i + 1}: ${label(a.detection.damage_type)} on ${label(a.detection.part)}`}
                >
                  <span className={styles.num}>{i + 1}</span>
                </button>
              );
            })}
          {q && !q.passed && (
            <div className={styles.rejected}>
              <strong>Not assessed</strong>
              <span>This photo is {q.reason}.</span>
            </div>
          )}
        </div>
      </div>

      {images.length > 1 && (
        <ul className={styles.strip}>
          {images.map((name, i) => {
            const count = assessments.filter((a) => a.image === name).length;
            const bad = quality.find((x) => x.image === name)?.passed === false;
            return (
              <li key={name}>
                <button
                  type="button"
                  className={styles.thumb}
                  aria-current={name === current || undefined}
                  onClick={() => onPick(name)}
                  aria-label={`Show photo ${i + 1}`}
                >
                  <img src={api.imageUrl(claimId, name)} alt="" />
                  {bad ? (
                    <span className={styles.tagBad}>Retake</span>
                  ) : count > 0 ? (
                    <span className={styles.tag}>{count}</span>
                  ) : null}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
