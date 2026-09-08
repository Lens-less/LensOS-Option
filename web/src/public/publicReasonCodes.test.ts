import { describe, expect, it } from "vitest";

import { readPublicReasonCode } from "./publicReasonCodes";

describe("readPublicReasonCode", () => {
  it.each(["constructor", "__proto__", "toString", "hasOwnProperty"])(
    "keeps inherited property %s on the unknown-code explanation path",
    (code) => {
      expect(readPublicReasonCode(code)).toEqual({
        title: "未收录的阻断原因",
        detail: "这是尚未收录公开解释的阻断原因。机器码仍会原样展示，页面不静默忽略或自行猜测。",
      });
    },
  );
});
