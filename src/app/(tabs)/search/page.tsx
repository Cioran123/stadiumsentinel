import SearchView from "@/app/components/SearchView";
import { searchIncidents } from "@/app/lib/search";

export const dynamic = "force-dynamic";

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q } = await searchParams;
  const query = q?.trim() ?? "";
  const initialData = query ? await searchIncidents(query) : null;
  return <SearchView key={query} initialQuery={query} initialData={initialData} />;
}
