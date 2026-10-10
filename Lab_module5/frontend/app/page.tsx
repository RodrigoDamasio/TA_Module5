import ResearchApp from "@/components/ResearchApp";

/** `?run=run_…` opens (and follows) that run. searchParams is a Promise in Next 16. */
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { run } = await searchParams;
  return <ResearchApp initialRunId={typeof run === "string" ? run : null} />;
}
