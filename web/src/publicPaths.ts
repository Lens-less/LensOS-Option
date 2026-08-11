export const APP_INDEX_HREF = "./index.html";
export const RAW_REPORT_HREF = "./research/report";
export const STATUS_PAGE_HREF = "./status.html";

export const FOOTER_LINKS = [
  { href: "./methodology.html", label: "方法论" },
  { href: "./disclaimer.html", label: "免责声明" },
  { href: "./privacy.html", label: "隐私政策" },
  { href: "./terms.html", label: "使用条款" },
  { href: STATUS_PAGE_HREF, label: "发布状态" },
] as const;

export const VIEW_LINKS = [
  { href: APP_INDEX_HREF, id: "evidence", label: "① 研究简报" },
  { href: `${APP_INDEX_HREF}?view=series`, id: "series", label: "② 波动时序" },
  {
    href: `${APP_INDEX_HREF}?view=workbench`,
    id: "workbench",
    label: "③ 候选工作台",
  },
  {
    href: `${APP_INDEX_HREF}?view=signal`,
    id: "signal",
    label: "④ 排序验证",
  },
] as const;
