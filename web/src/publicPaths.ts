export const APP_INDEX_HREF = "./index.html";
export const RAW_REPORT_HREF = "../research/report";

export const FOOTER_LINKS = [
  { href: "./methodology.html", label: "方法论" },
  { href: "./disclaimer.html", label: "免责声明" },
  { href: "./privacy.html", label: "隐私政策" },
  { href: "./terms.html", label: "使用条款" },
] as const;

export const NARRATIVE_LINKS = [
  { href: `${APP_INDEX_HREF}#vrp`, id: "vrp", label: "现在贵不贵" },
  { href: `${APP_INDEX_HREF}?view=series`, id: "series", label: "贵在哪里" },
  {
    href: `${APP_INDEX_HREF}#framework`,
    id: "framework",
    label: "卖它值不值",
  },
  {
    href: `${APP_INDEX_HREF}?view=signal`,
    id: "signal",
    label: "排序灵不灵",
  },
  {
    href: `${APP_INDEX_HREF}#limitations`,
    id: "limitations",
    label: "凭什么信",
  },
] as const;
