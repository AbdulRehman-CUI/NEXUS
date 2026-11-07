"use client";
import { useEffect, useRef, useState } from "react";

export function VirtualList<T>({
  items,
  rowHeight,
  render,
  className = "",
  label,
}: {
  items: T[];
  rowHeight: number;
  render: (item: T, index: number) => React.ReactNode;
  className?: string;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [window, setWindow] = useState({ top: 0, height: 600 });
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver(() =>
      setWindow((value) => ({ ...value, height: node.clientHeight })),
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const virtual = items.length > 60;
  const start = virtual
    ? Math.max(0, Math.floor(window.top / rowHeight) - 5)
    : 0;
  const end = virtual
    ? Math.min(items.length, start + Math.ceil(window.height / rowHeight) + 10)
    : items.length;
  return (
    <div
      ref={ref}
      className={`virtual-list ${className}`}
      aria-label={label}
      onScroll={(event) => {
        if (virtual) {
          const top = event.currentTarget.scrollTop;
          setWindow((value) => ({
            ...value,
            top,
          }));
        }
      }}
    >
      <div
        style={
          virtual
            ? { height: items.length * rowHeight, position: "relative" }
            : undefined
        }
      >
        {items.slice(start, end).map((item, index) => (
          <div
            key={start + index}
            className="virtual-row"
            style={
              virtual
                ? {
                    position: "absolute",
                    top: (start + index) * rowHeight,
                    height: rowHeight,
                    width: "100%",
                  }
                : undefined
            }
          >
            {render(item, start + index)}
          </div>
        ))}
      </div>
    </div>
  );
}
