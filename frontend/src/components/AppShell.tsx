import { useEffect, useRef } from "react";
import { NavLink, Outlet, useLocation } from "react-router";

import { t } from "../i18n";
import { SearchBar } from "./SearchBar";

/** The header from both sketches: tabs and the cuisine selector, the title, and the search bar. */
export function AppShell() {
  const { pathname } = useLocation();
  const main = useRef<HTMLElement>(null);
  const isFirstPage = useRef(true);

  // A new page should read as one: focus moves to its content, and the view returns to the top.
  useEffect(() => {
    if (isFirstPage.current) {
      isFirstPage.current = false;
      return;
    }
    main.current?.focus({ preventScroll: true });
    window.scrollTo?.(0, 0);
  }, [pathname]);

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        {t("app.skipToContent")}
      </a>
      <header className="app__header">
        <div className="app__top">
          <nav className="tabs" aria-label={t("nav.label")}>
            <NavLink to="/" end className="tabs__tab">
              {t("nav.search")}
            </NavLink>
            <NavLink to="/profile" className="tabs__tab">
              {t("nav.profile")}
            </NavLink>
          </nav>
          <label className="cuisine">
            <span className="cuisine__label">{t("cuisine.label")}</span>
            <select className="cuisine__select" disabled title={t("cuisine.unavailable")}>
              <option>{t("cuisine.all")}</option>
            </select>
          </label>
        </div>
        <p className="app__title">{t("app.name")}</p>
        <SearchBar />
      </header>
      <main id="main" ref={main} className="app__main" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="app__footer">{t("footer.disclaimer")}</footer>
    </div>
  );
}
