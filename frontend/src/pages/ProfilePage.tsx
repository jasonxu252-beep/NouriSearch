import { t } from "../i18n";

/** The sketch's profile page arrives with history and insights in milestone 8. */
export function ProfilePage() {
  return (
    <section className="page-message">
      <title>{`${t("profile.pageTitle")} | ${t("app.name")}`}</title>
      <h1 className="results__title">{t("profile.pageTitle")}</h1>
      <p>{t("profile.pageBody")}</p>
    </section>
  );
}
