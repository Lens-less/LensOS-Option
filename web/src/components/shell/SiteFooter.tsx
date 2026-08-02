import { FOOTER_LINKS } from "../../publicPaths";

export function SiteFooter(): React.JSX.Element {
  return (
    <footer className="page-footer">
      <div className="page-footer-copy">
        <span>LensOS Option · research only</span>
        <p>
          公开站仅供研究与信息用途。execution_authorization 永久 NO-GO；页面不连接下单、
          仓位 sizing 或自动执行。
        </p>
      </div>
      <nav aria-label="页脚链接" className="page-footer-links">
        {FOOTER_LINKS.map((link) => (
          <a href={link.href} key={link.href}>
            {link.label}
          </a>
        ))}
      </nav>
    </footer>
  );
}
