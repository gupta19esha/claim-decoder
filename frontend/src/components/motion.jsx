import { motion, useReducedMotion } from "framer-motion";

/*
  Movement should make reasoning feel considered, not decorative.

  ONE RULE ABOVE ALL: NOTHING HERE ANIMATES OPACITY FROM ZERO.

  Content that starts invisible and depends on a frame loop to become
  readable is content that can stay invisible. A throttled renderer, a
  backgrounded tab, a slow phone, an IntersectionObserver that never fires —
  any of those leaves the page blank, and this is opened by someone stressed
  and possibly ill in a hospital corridor. It is not a theoretical risk: the
  first build of this landing page rendered as an empty green rectangle
  because the reveal froze part-way, and the headline sat at opacity 0.09.

  So the reveal is transform only. If the animation never runs, the worst
  case is that a block sits eight pixels low, which nobody will ever notice.
  If it does run, content settles into place — it never slides in from
  off-screen, never bounces, never staggers for effect, and never celebrates.

  Everything collapses to a plain render when the reader has asked for
  reduced motion. Not a shortened animation, none.
*/

const TRAVEL = 8;

function useStill() {
  return useReducedMotion();
}

export function Settle({ as = "div", delay = 0, className, children, ...rest }) {
  const still = useStill();
  const Tag = motion[as] || motion.div;

  if (still) {
    const Plain = as;
    return (
      <Plain className={className} {...rest}>
        {children}
      </Plain>
    );
  }

  return (
    <Tag
      className={className}
      initial={{ y: TRAVEL }}
      whileInView={{ y: 0 }}
      viewport={{ once: true, margin: "0px 0px -8% 0px" }}
      transition={{ duration: 0.5, delay, ease: [0.2, 0, 0.2, 1] }}
      {...rest}
    >
      {children}
    </Tag>
  );
}

/* For content that arrives after the reader asked for it, rather than on
   scroll. Same rule: position only. */
export function Arrive({ as = "div", delay = 0, className, children, ...rest }) {
  const still = useStill();
  const Tag = motion[as] || motion.div;

  if (still) {
    const Plain = as;
    return (
      <Plain className={className} {...rest}>
        {children}
      </Plain>
    );
  }

  return (
    <Tag
      className={className}
      initial={{ y: TRAVEL }}
      animate={{ y: 0 }}
      transition={{ duration: 0.45, delay, ease: [0.2, 0, 0.2, 1] }}
      {...rest}
    >
      {children}
    </Tag>
  );
}

/* A rule that draws itself, so the page reads as typeset rather than
   assembled. Scale is safe: a rule stuck at scaleX(0) costs a hairline, not
   a paragraph. */
export function DrawnRule({ className = "" }) {
  const still = useStill();
  if (still) return <hr className={`border-t border-rule ${className}`} />;

  return (
    <motion.hr
      className={`origin-left border-t border-rule ${className}`}
      initial={{ scaleX: 0 }}
      whileInView={{ scaleX: 1 }}
      viewport={{ once: true }}
      transition={{ duration: 0.7, ease: [0.2, 0, 0.2, 1] }}
    />
  );
}
