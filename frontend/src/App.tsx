import { Route, Routes, useParams } from "react-router";

import { AppShell } from "./components/AppShell";
import { FoodPage } from "./pages/FoodPage";
import { ProfilePage } from "./pages/ProfilePage";
import { SearchPage } from "./pages/SearchPage";

/** The key gives each food a fresh page, so nothing selected on one carries to the next. */
function FoodRoute() {
  const { id } = useParams();
  return <FoodPage key={id} foodId={Number(id)} />;
}

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<SearchPage />} />
        <Route path="foods/:id" element={<FoodRoute />} />
        <Route path="profile" element={<ProfilePage />} />
      </Route>
    </Routes>
  );
}
