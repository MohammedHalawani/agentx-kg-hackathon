import {
  useEffect,
  useRef,
  useState,
  Suspense,
  type CSSProperties,
  type ReactNode,
} from "react";
import { NavLink, Link, Outlet, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  ScanSearch,
  ListChecks,
  Globe2,
  ScrollText,
  Settings2,
  Search,
  Bell,
  ChevronDown,
  ChevronsUpDown,
  HelpCircle,
  Moon,
  Sun,
  ArrowUpRight,
  CheckCheck,
  ArrowRight,
  FolderCheck,
  Activity,
  ShieldCheck,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import {
  Sidebar,
  SidebarProvider,
  SidebarHeader,
  SidebarContent,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarFooter,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { OperationalNotifications } from "@/components/operational-notifications";
import { useOperations } from "@/state/operations";
import { usePreferences } from "@/state/preferences";
import { StatusBadge } from "@/components/shared";
import { dateLabel, timeLabel } from "@/lib/dates";
import { asset } from "@/config";
import { displayId, searchText } from "@/domain/case-view";
const LAB_BUILD = import.meta.env.VITE_SUHAIL_DATA === "lab";

const LAST_CASE = "suhail.last-case";
function lastCase() {
  try {
    return sessionStorage.getItem(LAST_CASE);
  } catch {
    return null;
  }
}

const navigation = [
  {
    to: "/operations",
    en: "Operations",
    ar: "العمليات",
    icon: LayoutDashboard,
  },
  {
    to: LAB_BUILD ? "/cases/SHP-10482" : "/operations",
    en: "Investigation",
    ar: "التحقيق",
    icon: ScanSearch,
  },
  { to: "/decisions", en: "Decisions", ar: "القرارات", icon: ListChecks },
  { to: "/explore", en: "Explore", ar: "استكشاف", icon: Globe2 },
  { to: "/audit", en: "Audit", ar: "سجل التدقيق", icon: ScrollText },
];
function Navigation() {
  const { t, preferences } = usePreferences();
  const { cases, backend: fromBackend, connection } = useOperations();
  // Connected build: always the backend, so lab-only branches are removed at build time.
  const backend = !LAB_BUILD || fromBackend;
  const { setOpenMobile, isMobile } = useSidebar();
  const location = useLocation();
  const [workspace, setWorkspace] = useState(false);
  const [help, setHelp] = useState(false);
  const attention = cases.filter((c) => c.status === "human_review").length;
  // Backend: "Investigation" opens the case being viewed, the last one opened, or the queue.
  const openCase = location.pathname.startsWith("/cases/")
    ? decodeURIComponent(location.pathname.split("/")[2] ?? "")
    : null;
  useEffect(() => {
    if (!backend || !openCase) return;
    try {
      sessionStorage.setItem(LAST_CASE, openCase);
    } catch {
      /* Session storage is optional. */
    }
  }, [backend, openCase]);
  const remembered = openCase ?? lastCase();
  const investigation = !backend
    ? "/cases/SHP-10482"
    : remembered && cases.some((c) => c.id === remembered)
      ? `/cases/${remembered}`
      : cases[0]
        ? `/cases/${cases[0].id}`
        : "/operations";
  const online = connection?.state === "online";
  const closeMobile = () => {
    if (isMobile) setOpenMobile(false);
  };
  return (
    <>
      <Sidebar
        collapsible="icon"
        side={preferences.language === "ar" ? "right" : "left"}
        className="suhail-sidebar"
      >
        <SidebarHeader className="brand-header">
          <Link to="/operations" className="brand" onClick={closeMobile}>
            <img src={asset("suhail.svg")} alt="" />
            <span>
              suhail<span className="brand-arabic">سهيل</span>
            </span>
          </Link>
          <span className="brand-caption">
            {t("LOGISTICS INTELLIGENCE", "الذكاء اللوجستي")}
          </span>
        </SidebarHeader>
        <SidebarContent>
          <div className="workspace-selector">
            <Button
              variant="outline"
              onClick={() => setWorkspace(true)}
              aria-label="Workspace details"
            >
              <span className="workspace-icon">S</span>
              <span className="workspace-text">
                <b>{backend ? "Suhail Operations" : "SPL Operations"}</b>
                <small>
                  {backend
                    ? t("Synthetic network", "شبكة اصطناعية")
                    : t("Saudi network", "شبكة المملكة")}
                </small>
              </span>
              <ChevronsUpDown size={13} />
            </Button>
          </div>
          <SidebarGroup>
            <SidebarGroupLabel>
              {t("WORKSPACE", "مساحة العمل")}
            </SidebarGroupLabel>
            <SidebarMenu>
              {navigation.map((item) => (
                <SidebarMenuItem key={item.en}>
                  <SidebarMenuButton
                    asChild
                    isActive={
                      item.en === "Investigation"
                        ? location.pathname.startsWith("/cases/")
                        : location.pathname === item.to
                    }
                    tooltip={t(item.en, item.ar)}
                  >
                    <NavLink
                      to={item.en === "Investigation" ? investigation : item.to}
                      onClick={closeMobile}
                    >
                      <item.icon size={17} />
                      <span>{t(item.en, item.ar)}</span>
                      {item.en === "Decisions" && attention > 0 && (
                        <span className="nav-counter">{attention}</span>
                      )}
                    </NavLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroup>
          <SidebarGroup className="secondary-nav">
            <SidebarGroupLabel>
              {t("PREFERENCES", "التفضيلات")}
            </SidebarGroupLabel>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  asChild
                  isActive={location.pathname === "/settings"}
                  tooltip={t("Settings", "الإعدادات")}
                >
                  <NavLink to="/settings" onClick={closeMobile}>
                    <Settings2 size={17} />
                    <span>{t("Settings", "الإعدادات")}</span>
                  </NavLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter>
          <div className="sidebar-system">
            <span className={!backend || online ? "live-dot" : "paused-dot"} />
            <span>
              {backend
                ? online
                  ? t("Backend connected", "الخادم متصل")
                  : connection?.state === "connecting"
                    ? t("Connecting to backend", "جارٍ الاتصال بالخادم")
                    : t("Backend unreachable", "تعذر الوصول إلى الخادم")
                : t("Local simulation", "محاكاة محلية")}
              <small>
                {backend
                  ? t("Synthetic dataset", "بيانات اصطناعية")
                  : t("Isolated UI lab", "مختبر واجهة مستقل")}
              </small>
            </span>
            <ShieldCheck size={14} />
          </div>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                tooltip={t("Workspace guide", "دليل مساحة العمل")}
                onClick={() => setHelp(true)}
              >
                <HelpCircle size={17} />
                <span>{t("Workspace guide", "دليل مساحة العمل")}</span>
                <ArrowUpRight size={12} className="ms-auto" />
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem>
              <SidebarMenuButton
                asChild
                className="operator-button"
                tooltip={
                  backend
                    ? (connection?.operator?.actorId ?? "Operator")
                    : "Noura Al-Salem"
                }
              >
                <Link to="/settings" onClick={closeMobile}>
                  <span className="avatar">{backend ? "OP" : "NA"}</span>
                  <span className="operator-name">
                    {backend ? (
                      <span dir="ltr">
                        {connection?.operator?.actorId ??
                          t("No operator session", "لا توجد جلسة مشغل")}
                      </span>
                    ) : (
                      t("Noura Al-Salem", "نورة السالم")
                    )}
                    <small>
                      {backend
                        ? t("Local operator session", "جلسة مشغل محلية")
                        : t("Operations supervisor", "مشرفة العمليات")}
                    </small>
                  </span>
                  <ChevronDown size={13} className="ms-auto" />
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
      </Sidebar>
      <Dialog open={workspace} onOpenChange={setWorkspace}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {backend
                ? t("Suhail Operations workspace", "مساحة عمليات سهيل")
                : t("SPL Operations workspace", "مساحة عمليات سبل")}
            </DialogTitle>
            <DialogDescription>
              {backend
                ? t(
                    "The Suhail operations workspace, connected to the Suhail backend.",
                    "مساحة عمليات سهيل، متصلة بخادم سهيل.",
                  )
                : t(
                "A standalone Suhail frontend lab for the Saudi logistics network.",
                "مختبر واجهة سهيل المستقل للشبكة اللوجستية السعودية.",
              )}
            </DialogDescription>
          </DialogHeader>
          <div className="info-box">
            <ShieldCheck size={20} />
            <p>
              {backend
                ? t(
                    "Shipments and evidence come from a synthetic logistics dataset served by the Suhail backend. It is not SPL operational data. Investigations, decisions and outcomes are recorded by the backend, not by this browser.",
                    "الشحنات والأدلة من مجموعة بيانات لوجستية اصطناعية يقدمها خادم سهيل. ليست بيانات تشغيلية لسبل. يسجل الخادم التحقيقات والقرارات والنتائج، لا هذا المتصفح.",
                  )
                : t(
                "All shipments, evidence, decisions, and outcomes are synthetic. State is saved in this browser. The lab has no connection to the operational database.",
                "جميع الشحنات والأدلة والقرارات والنتائج محاكاة. تُحفظ الحالة في هذا المتصفح، ولا يوجد اتصال بقاعدة البيانات التشغيلية.",
              )}
            </p>
          </div>
        </DialogContent>
      </Dialog>
      <Sheet open={help} onOpenChange={setHelp}>
        <SheetContent className="guide-sheet">
          <SheetHeader>
            <SheetTitle>
              {t("A clearer path to resolution", "مسار أوضح لحل الاستثناءات")}
            </SheetTitle>
            <SheetDescription>
              {t(
                backend
                  ? "A quick guide to the Suhail workspace."
                  : "A quick guide to the Suhail UI lab.",
                backend ? "دليل سريع لمساحة عمل سهيل." : "دليل سريع لمختبر واجهة سهيل.",
              )}
            </SheetDescription>
          </SheetHeader>
          <div className="sheet-body">
            <Guide
              icon={<LayoutDashboard />}
              title={t("Monitor operations", "مراقبة العمليات")}
            >
              {t(
                "Search and filter incoming exceptions. Newest cases appear first; automatic processing picks the oldest eligible case.",
                "ابحث في الاستثناءات الواردة وصفيها. تُعرض الأحدث أولاً، وتبدأ المعالجة التلقائية بأقدم حالة مؤهلة.",
              )}
            </Guide>
            <Guide
              icon={<ScanSearch />}
              title={t("Follow the evidence", "تتبع الأدلة")}
            >
              {t(
                "Open a shipment to see its map and knowledge graph together. Select a scan on either view to focus the same evidence in both.",
                "افتح الشحنة لعرض الخريطة والرسم المعرفي معاً، واختر دليلاً لإبرازه في العرضين.",
              )}
            </Guide>
            <Guide
              icon={<ListChecks />}
              title={t("Make explicit decisions", "اتخاذ قرارات واضحة")}
            >
              {t(
                "Review the proposed action and provide a reason before approving or rejecting. Only a separately verified outcome resolves a case.",
                "راجع الإجراء المقترح وقدم سبباً للموافقة أو الرفض. لا تُحل الحالة إلا بعد تحقق مستقل من النتيجة.",
              )}
            </Guide>
            <div className="shortcut-row">
              <kbd>Ctrl K</kbd>
              <span>{t("Search shipments", "البحث عن الشحنات")}</span>
            </div>
            <div className="shortcut-row">
              <kbd>Ctrl B</kbd>
              <span>{t("Toggle sidebar", "تبديل الشريط الجانبي")}</span>
            </div>
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
function Guide({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="guide-item">
      {icon}
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
function TopBar() {
  const { t, preferences, update } = usePreferences();
  const { cases, events, backend: fromBackend, connection, service } = useOperations();
  // Connected build: always the backend, so lab-only branches are removed at build time.
  const backend = !LAB_BUILD || fromBackend;
  const location = useLocation();
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [notifications, setNotifications] = useState(false);
  const title = location.pathname.startsWith("/cases")
    ? t("Investigation", "التحقيق")
    : t(
        navigation.find((n) => n.to === location.pathname)?.en ?? "Settings",
        navigation.find((n) => n.to === location.pathname)?.ar ?? "الإعدادات",
      );
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setSearchOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
  const results = cases.filter((c) =>
    searchText(c).includes(query.toLowerCase()),
  );
  return (
    <>
      <header className="topbar">
        <div className="topbar-location">
          <SidebarTrigger
            aria-label={t("Toggle sidebar", "تبديل الشريط الجانبي")}
          />
          <span className="breadcrumb-root">
            {t("Workspace", "مساحة العمل")}
          </span>
          <span className="breadcrumb-sep">/</span>
          <b>{title}</b>
        </div>
        <div className="topbar-actions">
          <Button
            variant="outline"
            size="sm"
            className="global-search"
            onClick={() => setSearchOpen(true)}
          >
            <Search size={14} />
            <span>{t("Search shipments…", "البحث عن الشحنات…")}</span>
            <kbd>Ctrl K</kbd>
          </Button>
          <span
            className="environment-badge"
            title={backend ? (connection?.error ?? undefined) : undefined}
          >
            <span
              className={
                !backend || connection?.state === "online"
                  ? "live-dot"
                  : "paused-dot"
              }
            />
            {backend
              ? connection?.state === "online"
                ? t("Synthetic data", "بيانات اصطناعية")
                : connection?.state === "connecting"
                  ? t("Connecting…", "جارٍ الاتصال…")
                  : t("Backend offline", "الخادم غير متصل")
              : t("UI lab", "مختبر الواجهة")}
          </span>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() =>
              update({ language: preferences.language === "en" ? "ar" : "en" })
            }
            aria-label={t("Switch to Arabic", "Switch to English")}
            className="language-button"
          >
            {preferences.language === "en" ? "EN" : "ع"}
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={t("Toggle theme", "تبديل المظهر")}
            onClick={() =>
              update({
                theme: preferences.theme === "light" ? "dark" : "light",
              })
            }
          >
            {preferences.theme === "light" ? (
              <Moon size={15} />
            ) : (
              <Sun size={15} />
            )}
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={t("Notifications", "الإشعارات")}
            onClick={() => {
              // Backend: the activity list reads the audit ledger.
              void service.loadAudit?.();
              setNotifications(true);
            }}
          >
            <Bell size={16} />
          </Button>
        </div>
      </header>
      {backend &&
        connection &&
        (connection.state === "offline" || connection.state === "degraded") && (
          <div className="backend-notice" role="status">
            <ShieldCheck size={14} />
            <span>
              {connection.state === "offline"
                ? t(
                    "The Suhail backend is not reachable. Nothing is shown until it answers; no stand-in data is used.",
                    "تعذر الوصول إلى خادم سهيل. لا يُعرض شيء حتى يستجيب، ولا تُستخدم بيانات بديلة.",
                  )
                : t(
                    `The connection to the backend was interrupted. Showing what was last read at ${connection.lastSyncAt ? timeLabel(connection.lastSyncAt) : "—"} AST; it may be out of date.`,
                    `انقطع الاتصال بالخادم. يُعرض آخر ما قُرئ عند ${connection.lastSyncAt ? timeLabel(connection.lastSyncAt) : "—"} بتوقيت السعودية، وقد يكون قديماً.`,
                  )}
              {connection.error ? ` (${connection.error})` : ""}
            </span>
          </div>
        )}
      <Dialog open={searchOpen} onOpenChange={setSearchOpen}>
        <DialogContent className="search-dialog">
          <DialogHeader>
            <DialogTitle>
              {t("Search shipments", "البحث عن الشحنات")}
            </DialogTitle>
            <DialogDescription>
              {t(
                "Search by shipment ID, exception, or destination.",
                "ابحث بمعرف الشحنة أو الاستثناء أو الوجهة.",
              )}
            </DialogDescription>
          </DialogHeader>
          <Input
            autoFocus
            aria-label="Global shipment search"
            placeholder={
              backend
                ? t("Shipment, case or city…", "شحنة أو حالة أو مدينة…")
                : "SHP-10482, barcode, Dammam…"
            }
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="search-results">
            {results.slice(0, 8).map((c) => (
              <Link
                key={c.id}
                to={`/cases/${c.id}`}
                onClick={() => setSearchOpen(false)}
              >
                <span>
                  <b>{displayId(c)}</b>
                  <small>
                    {c.issue} · {c.shipment.destination}
                  </small>
                </span>
                <StatusBadge status={c.status} c={c} />
              </Link>
            ))}
            {results.length === 0 && (
              <p>{t("No matching shipments.", "لا توجد شحنات مطابقة.")}</p>
            )}
          </div>
        </DialogContent>
      </Dialog>
      <Sheet open={notifications} onOpenChange={setNotifications}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>
              {t("Operational activity", "النشاط التشغيلي")}
            </SheetTitle>
            <SheetDescription>
              {backend
                ? t(
                    "Recent events recorded in the backend audit ledger.",
                    "أحداث حديثة مسجلة في سجل تدقيق الخادم.",
                  )
                : t(
                    "Recent events from the local simulation.",
                    "أحداث حديثة من المحاكاة المحلية.",
                  )}
            </SheetDescription>
          </SheetHeader>
          <div className="sheet-body">
            {[...events]
              .sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp))
              .filter((e) => e.caseId)
              .slice(0, 12)
              .map((e) => (
                <Link
                  className="notification-item"
                  key={e.id}
                  to={`/cases/${e.caseId}`}
                  onClick={() => setNotifications(false)}
                >
                  <Activity size={16} />
                  <div>
                    <b>{e.title}</b>
                    <p>{e.detail}</p>
                    <small>
                      {e.shipmentId ?? e.caseId} · {timeLabel(e.timestamp)} ·{" "}
                      {LAB_BUILD && e.simulated
                        ? t("simulated", "محاكاة")
                        : t("backend", "الخادم")}
                    </small>
                  </div>
                </Link>
              ))}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
function ResolutionTransfer() {
  const { cases } = useOperations();
  const { t } = usePreferences();
  const { backend: fromBackend, connection } = useOperations();
  // Connected build: always the backend, so lab-only branches are removed at build time.
  const backend = !LAB_BUILD || fromBackend;
  const resolved = cases
    .filter((c) => c.status === "resolved")
    .map((c) => c.id);
  const previous = useRef(new Set(resolved));
  // Backend: cases already resolved when the queue is first read are not "just transferred".
  const primed = useRef(!backend);
  const [recent, setRecent] = useState<string | null>(null);
  useEffect(() => {
    const next = cases.filter((c) => c.status === "resolved");
    const added = next.find((c) => !previous.current.has(c.id));
    previous.current = new Set(next.map((c) => c.id));
    if (!primed.current) {
      if (connection?.lastSyncAt) primed.current = true;
      return;
    }
    if (added) setRecent(displayId(added));
  }, [cases, connection?.lastSyncAt]);
  useEffect(() => {
    if (!recent) return;
    const timer = setTimeout(() => setRecent(null), 4200);
    return () => clearTimeout(timer);
  }, [recent]);
  return (
    <AnimatePresence>
      {recent && (
        <motion.div
          className="resolution-transfer"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 8 }}
        >
          <FolderCheck size={23} />
          <span>
            <b>{recent}</b>
            <small>
              {t(
                "Transferred to verified resolutions",
                "نُقلت إلى الحلول المتحققة",
              )}
            </small>
          </span>
          <ArrowRight size={16} />
          <CheckCheck size={18} />
        </motion.div>
      )}
    </AnimatePresence>
  );
}
export function AppShell() {
  const location = useLocation();
  const { t } = usePreferences();
  const { backend: fromBackend, connection } = useOperations();
  // Connected build: always the backend, so lab-only branches are removed at build time.
  const backend = !LAB_BUILD || fromBackend;
  return (
    <SidebarProvider
      style={
        {
          "--sidebar-width": "220px",
          "--sidebar-width-icon": "64px",
        } as CSSProperties
      }
    >
      <Navigation />
      <div className="app-main">
        <TopBar />
        <motion.main
          key={location.pathname}
          className="page-content"
          initial={{ opacity: 0, y: 3 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <Suspense
            fallback={
              <div
                className="space-y-6"
                aria-label="Loading workspace"
                role="status"
              >
                <div className="space-y-3">
                  <Skeleton className="h-7 w-48" />
                  <Skeleton className="h-4 w-72" />
                </div>
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-[450px] w-full" />
              </div>
            }
          >
            <Outlet />
          </Suspense>
        </motion.main>
        <footer className="app-footer">
          <span>
            SUHAIL <span>·</span>{" "}
            {t("Logistics intelligence", "الذكاء اللوجستي")}
          </span>
          <span>
            {backend
              ? t(
                  "Synthetic data · Suhail backend",
                  "بيانات اصطناعية · خادم سهيل",
                )
              : t(
                  "Synthetic data · local simulation",
                  "بيانات اصطناعية · محاكاة محلية",
                )}
            <span>·</span>{" "}
            {backend
              ? connection?.asOf
                ? `${t("dataset clock", "ساعة البيانات")} ${dateLabel(connection.asOf).toUpperCase()}`
                : "—"
              : "09 OCT 2026"}
          </span>
        </footer>
      </div>
      <ResolutionTransfer />
      <OperationalNotifications />
    </SidebarProvider>
  );
}
