/*
  The clause exhibit. The signature element of the product.

  Verbatim policy text, the page it sits on, and an explicit invitation to go
  and check. It is the only thing on any screen allowed to break the page
  margin, because it is the evidence and everything else is commentary.

  It carries no colour. Someone will print this and hand it to a grievance
  officer, so it is built from rule weight, mono and a printer's folio — a
  black and white photocopy loses nothing. See @media print in theme.css.

  Never paraphrase what goes in here. The text prop must be a verbatim string
  from the corpus.
*/

/* Policy clauses arrive as one block containing lettered sub-clauses. Left as
   is they are a wall. Breaking on the lettering makes them readable without
   altering a character. */
export function clauseParts(text) {
  return String(text || "")
    .split(/(?=(?:^|\s)(?:[a-hA-H]\.|[iv]{1,4}\.)\s)/g)
    .map((p) => p.trim())
    .filter(Boolean);
}

export default function Exhibit({
  title,
  page,
  source,
  text,
  meta = [],
  note,
}) {
  const parts = clauseParts(text);

  return (
    <figure
      className="exhibit relative -mx-5 border-y-1 border-t-[3px] border-ink
                 bg-card sm:mx-0 sm:border-x sm:border-rule
                 lg:grid lg:grid-cols-[8rem_minmax(0,44rem)] lg:gap-x-8"
    >
      {/* The folio. In the margin on desktop, in the top rule on mobile —
          a printer's mark, not a badge. */}
      <div
        className="exhibit-folio flex items-baseline justify-between gap-3
                   border-b border-rule-soft px-5 pt-3 pb-2
                   lg:col-start-1 lg:row-start-1 lg:block lg:border-0
                   lg:px-0 lg:pt-6 lg:pl-6 lg:text-right"
      >
        <span className="folio text-ink">Page {page}</span>
        {source && (
          <span className="folio text-ink-soft lg:mt-1 lg:block">
            {source}
          </span>
        )}
      </div>

      <div className="px-5 pt-5 pb-6 lg:col-start-2 lg:row-start-1 lg:py-6 lg:pr-6">
        {title && (
          <figcaption className="wrap-verbatim mb-4 font-doc text-lg leading-snug font-semibold text-ink sm:text-xl">
            {title}
          </figcaption>
        )}

        <blockquote className="wrap-verbatim space-y-3 font-quote text-[0.8125rem] leading-[1.8] text-ink-verbatim">
          {parts.map((p, i) => (
            <p key={i} className={i > 0 ? "pl-4 -indent-4" : undefined}>
              {p}
            </p>
          ))}
        </blockquote>

        {meta.length > 0 && (
          <div className="mt-5 flex flex-wrap gap-1.5">
            {meta.map((m) => (
              <span
                key={m}
                className="folio bg-paper-chip px-2 py-1 text-ink-2"
              >
                {m}
              </span>
            ))}
          </div>
        )}

        <p className="mt-5 border-t border-rule-soft pt-3 font-doc text-sm text-ink-soft">
          {note || (
            <>
              Quoted word for word. Open your policy at page {page} and read it
              yourself.
            </>
          )}
        </p>
      </div>
    </figure>
  );
}
