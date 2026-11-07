"use client";
import Link from "next/link";
import { useEffect, useRef } from "react";
import { LazyMotion, useReducedMotion } from "motion/react";
import * as m from "motion/react-m";

let brandRevealed = false;
export const motionTiming = { fast: 160, expand: 240, enter: 320, logo: 1250 };
const loadMotionFeatures = () =>
  import("./motion-features").then((module) => module.default);

export function Brand() {
  const ref = useRef<HTMLAnchorElement>(null);
  useEffect(() => {
    if (!brandRevealed && ref.current) {
      ref.current.dataset.reveal = "true";
      brandRevealed = true;
    }
  }, []);
  return (
    <Link href="/" className="brand" aria-label="NEXUS home" ref={ref}>
      <span className="brand-letters" aria-hidden="true">
        {"NEXUS".split("").map((letter, index) => (
          <span key={index} style={{ animationDelay: `${index * 65}ms` }}>
            {letter}
          </span>
        ))}
      </span>
      <span className="brand-accent" aria-hidden="true" />
      <span className="brand-version">WORKSPACE</span>
    </Link>
  );
}

export function PageTransition({ children }: { children: React.ReactNode }) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    window.dispatchEvent(new Event("nexus-route-ready"));
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.setAttribute("data-revealed", "true");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.05 },
    );
    function observeNewCards() {
      el?.querySelectorAll(
        ".settings-card:not([data-motion-ready]),.document-row:not([data-motion-ready]),.starter-grid > :not([data-motion-ready]),.sync-card:not([data-motion-ready])",
      ).forEach((card, index) => {
        card.setAttribute("data-motion-ready", "true");
        (card as HTMLElement).style.setProperty(
          "--stagger",
          String(Math.min(index, 5)),
        );
        observer.observe(card);
      });
    }
    observeNewCards();
    const additions = new MutationObserver(observeNewCards);
    additions.observe(el, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      additions.disconnect();
    };
  }, []);
  return (
    <LazyMotion features={loadMotionFeatures} strict>
      <m.div
        className="page-transition"
        ref={ref}
        initial={reduce ? false : { opacity: 0, y: 7 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{
          duration: reduce ? 0 : motionTiming.enter / 1000,
          ease: [0.22, 1, 0.36, 1],
        }}
      >
        {children}
      </m.div>
    </LazyMotion>
  );
}

export function navigateWithTransition(
  push: (href: string) => void,
  href: string,
) {
  if (
    !document.startViewTransition ||
    matchMedia("(prefers-reduced-motion: reduce)").matches
  ) {
    push(href);
    return;
  }
  const transition = document.startViewTransition(
    () =>
      new Promise<void>((resolve) => {
        const done = () => {
          clearTimeout(timer);
          window.removeEventListener("nexus-route-ready", done);
          resolve();
        };
        window.addEventListener("nexus-route-ready", done, { once: true });
        const timer = setTimeout(done, 450);
        push(href);
      }),
  );
  void transition.finished.catch(() => {});
}

export function Skeleton({
  label = "Loading your workspace",
}: {
  label?: string;
}) {
  return (
    <div className="skeleton-scene" role="status" aria-label={label}>
      <span className="skeleton-line short" />
      <span className="skeleton-line" />
      <div className="skeleton-cards">
        <span />
        <span />
        <span />
      </div>
      <span className="sr-only">{label}</span>
    </div>
  );
}
