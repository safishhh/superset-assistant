type HeaderIconName =
  | "admin"
  | "history"
  | "knowledge"
  | "plus"
  | "expand"
  | "compress"
  | "download"
  | "panel"
  | "floating"
  | "close";

export function HeaderIcon({ name }: { name: HeaderIconName }) {
  const common = {
    width: 15,
    height: 15,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.9,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  switch (name) {
    case "admin":
      return (
        <svg {...common}>
          <path d="M12 3.5 19 6v5c0 4.3-2.9 7.4-7 8.9-4.1-1.5-7-4.6-7-8.9V6z" />
          <path d="M9.5 12.2 11.4 14l3.3-3.6" />
        </svg>
      );
    case "history":
      return (
        <svg {...common}>
          <path d="M3.2 12a8.8 8.8 0 1 0 2.6-6.3L3.2 8.2" />
          <path d="M3.2 3.4v4.8h4.8" />
          <path d="M12 7.6V12l3 1.8" />
        </svg>
      );
    case "knowledge":
      return (
        <svg {...common}>
          <path d="M4.5 5.5A2 2 0 0 1 6.5 3.5H19.5v14H6.5a2 2 0 0 0-2 2z" />
          <path d="M4.5 5.5v14a2 2 0 0 0 2 2h13" />
          <path d="M8.5 8.5h7M8.5 12h5" />
        </svg>
      );
    case "plus":
      return (
        <svg {...common}>
          <path d="M12 5v14M5 12h14" />
        </svg>
      );
    case "expand":
      return (
        <svg {...common}>
          <path d="M9 3.5H3.5V9M15 3.5h5.5V9M9 20.5H3.5V15M15 20.5h5.5V15" />
        </svg>
      );
    case "compress":
      return (
        <svg {...common}>
          <path d="M3.5 9H9V3.5M20.5 9H15V3.5M3.5 15H9v5.5M20.5 15H15v5.5" />
        </svg>
      );
    case "download":
      return (
        <svg {...common}>
          <path d="M12 3.5v11" />
          <path d="m7.5 10.5 4.5 4.5 4.5-4.5" />
          <path d="M4 20.5h16" />
        </svg>
      );
    case "panel":
      return (
        <svg {...common}>
          <rect x="3.5" y="4.5" width="17" height="15" rx="2.5" />
          <path d="M15.5 4.5v15" />
        </svg>
      );
    case "floating":
      return (
        <svg {...common}>
          <rect x="3.5" y="5" width="13" height="10.5" rx="2" />
          <path d="M8 20h10.5a2 2 0 0 0 2-2V9.5" />
        </svg>
      );
    case "close":
      return (
        <svg {...common}>
          <path d="m6 6 12 12M18 6 6 18" />
        </svg>
      );
  }
}

export function ThumbIcon({ up, active }: { up: boolean; active: boolean }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill={active ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={up ? undefined : { transform: "rotate(180deg)" }}
      aria-hidden
    >
      <path d="M7 10.5 10.6 4c1 .1 1.9 1 1.9 2V9h4.4c1.2 0 2.1 1.1 1.8 2.3l-1.5 6.6A2.4 2.4 0 0 1 14.8 20H7" />
      <path d="M7 10.5H5.4A1.9 1.9 0 0 0 3.5 12.4v5.7A1.9 1.9 0 0 0 5.4 20H7" />
    </svg>
  );
}
