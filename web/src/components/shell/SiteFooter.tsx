import { FOOTER_LINKS } from "../../publicPaths";

interface SiteFooterProps {
  leadingLinks?: ReadonlyArray<{ href: string; label: string }>;
}

export function SiteFooter({
  leadingLinks = [],
}: SiteFooterProps = {}): React.JSX.Element {
  const links = [...leadingLinks, ...FOOTER_LINKS];

  return (
    <footer className="page-footer">
      <div className="page-footer-copy">
        <span>LensOS Option · RESEARCH_ONLY · NO_TRADE</span>
        <p>
          公开站仅供研究与信息用途。执行授权始终关闭；页面不连接下单、仓位计算或自动执行。
        </p>
      </div>
      <nav aria-label="页脚链接" className="page-footer-links">
        {links.map((link) => (
          <a href={link.href} key={link.href}>
            {link.label}
          </a>
        ))}
      </nav>
    </footer>
  );
}
