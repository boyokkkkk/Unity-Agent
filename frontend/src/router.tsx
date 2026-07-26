import { createContext, type MouseEvent, type ReactNode, useContext, useEffect, useState } from "react";

type Navigate = (to: string, options?: { replace?: boolean }) => void;
const RouterContext = createContext<{ pathname: string; navigate: Navigate } | null>(null);

export function RouterProvider({ children }: { children: ReactNode }) {
  const [pathname, setPathname] = useState(window.location.pathname);
  useEffect(() => {
    const update = () => setPathname(window.location.pathname);
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  const navigate: Navigate = (to, options) => {
    window.history[options?.replace ? "replaceState" : "pushState"]({}, "", to);
    setPathname(window.location.pathname);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  return <RouterContext.Provider value={{ pathname, navigate }}>{children}</RouterContext.Provider>;
}

function useRouter() {
  const value = useContext(RouterContext);
  if (!value) throw new Error("RouterProvider is missing");
  return value;
}

export function useLocation() { return { pathname: useRouter().pathname }; }
export function useNavigate() { return useRouter().navigate; }
export function useParams(): { runId?: string } {
  const match = useRouter().pathname.match(/^\/runs\/([^/]+)$/);
  return { runId: match ? decodeURIComponent(match[1]) : undefined };
}

interface LinkProps { to: string; className?: string; children: ReactNode; "aria-label"?: string; }
export function Link({ to, className, children, ...props }: LinkProps) {
  const navigate = useNavigate();
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
      event.preventDefault(); navigate(to);
    }
  }
  return <a href={to} className={className} onClick={follow} {...props}>{children}</a>;
}

export function NavLink({ to, className, children }: {
  to: string; className: (state: { isActive: boolean }) => string; children: ReactNode;
}) {
  const { pathname } = useLocation();
  const runDetailActive = /^\/runs\/[^/]+$/.test(pathname) && pathname !== "/runs/new";
  const isActive = to === "/runs" ? pathname === "/runs" || runDetailActive : pathname === to;
  return <Link to={to} className={className({ isActive })}>{children}</Link>;
}

export function Navigate({ to, replace = false }: { to: string; replace?: boolean }) {
  const navigate = useNavigate();
  useEffect(() => navigate(to, { replace }), [navigate, replace, to]);
  return null;
}
