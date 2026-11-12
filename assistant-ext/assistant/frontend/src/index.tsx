import { chat } from "@apache-superset/core";

import ChatPanel from "./ChatPanel";
import ChatTrigger from "./ChatTrigger";
import { injectStyles } from "./styles";

injectStyles();

chat.registerChat(
  {
    id: "dataagent.assistant",
    name: "数据分析助手",
    description: "用自然语言问数、做归因拆解",
  },
  ChatTrigger,
  ChatPanel,
);

