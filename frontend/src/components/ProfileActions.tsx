import { t } from "../i18n";

/** The sketch's "Add to profile", split into two clear actions. History arrives in milestone 8. */
export function ProfileActions() {
  return (
    <section className="panel panel--profile" aria-labelledby="profile-actions-title">
      <h2 id="profile-actions-title" className="panel__title">
        {t("profile.title")}
      </h2>
      <p className="panel__empty">{t("profile.none")}</p>
      <div className="profile-actions">
        <button type="button" className="button" disabled title={t("profile.unavailable")}>
          {t("profile.ate")}
        </button>
        <button type="button" className="button" disabled title={t("profile.unavailable")}>
          {t("profile.add")}
        </button>
      </div>
      <p className="panel__note">{t("profile.unavailable")}</p>
    </section>
  );
}
