declare module "@apache-superset/core" {
  import type { ComponentType } from "react";

  export interface Disposable {
    dispose(): void;
  }

  export type Event<T> = (listener: (value: T) => void) => Disposable;

  export namespace chat {
    interface ChatDescriptor {
      id: string;
      name: string;
      description?: string;
    }

    type DisplayMode = "floating" | "panel";

    function registerChat(
      chat: ChatDescriptor,
      trigger: ComponentType,
      panel: ComponentType,
    ): Disposable;
    function getChat(): ChatDescriptor | undefined;
    function open(): void;
    function close(): void;
    function isOpen(): boolean;
    function getDisplayMode(): DisplayMode;
    function setDisplayMode(mode: DisplayMode): void;
    const onDidOpen: Event<void>;
    const onDidClose: Event<void>;
    const onDidChangeDisplayMode: Event<DisplayMode>;
  }

  export namespace sqlLab {
    interface Editor {
      getValue(): string;
    }

    interface Tab {
      id: string;
      title: string;
      databaseId: number;
      catalog: string | null;
      schema: string | null;
      getEditor(): Promise<Editor>;
    }

    function getCurrentTab(): Tab | undefined;
  }

  export type SupersetTheme = Record<string, any>;

  export namespace theme {
    function useTheme(): SupersetTheme;
  }
}
