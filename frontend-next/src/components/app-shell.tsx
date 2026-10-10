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
import { timeLabel } from "@/lib/dates";

const navigation = [
  {
    to: "/operations",
    en: "Operations",
    ar: "العمليات",
    icon: LayoutDashboard,
  },
  {
    to: "/cases/SHP-10482",
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
  const { cases } = useOperations();
  const { setOpenMobile, isMobile } = useSidebar();
  const location = useLocation();
  const [workspace, setWorkspace] = useState(false);
  const [help, setHelp] = useState(false);
  const attention = cases.filter((c) => c.status === "human_review").length;
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
            <img src="/suhail.svg" alt="" />
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
                <b>SPL Operations</b>
                <small>{t("Saudi network", "شبكة المملكة")}</small>
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
                    <NavLink to={item.to} onClick={closeMobile}>
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
            <span className="live-dot" />
            <span>
              {t("Local simulation", "محاكاة محلية")}
              <small>{t("Isolated UI lab", "مختبر واجهة مستقل")}</small>
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
                tooltip="Noura Al-Salem"
              >
                <Link to="/settings" onClick={closeMobile}>
                  <span className="avatar">NA</span>
                  <span className="operator-name">
                    {t("Noura Al-Salem", "نورة السالم")}
                    <small>
                      {t("Operations supervisor", "مشرفة العمليات")}
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
              {t("SPL Operations workspace", "مساحة عمليات سبل")}
            </DialogTitle>
            <DialogDescription>
              {t(
                "A standalone Suhail frontend lab for the Saudi logistics network.",
                "مختبر واجهة سهيل المستقل للشبكة اللوجستية السعودية.",
              )}
            </DialogDescription>
          </DialogHeader>
          <div className="info-box">
            <ShieldCheck size={20} />
            <p>
              {t(
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
                "A quick guide to the Suhail UI lab.",
                "دليل سريع لمختبر واجهة سهيل.",
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
  const { cases, events } = useOperations();
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
    `${c.id} ${c.issue} ${c.shipment.destination}`
      .toLowerCase()
      .includes(query.toLowerCase()),
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
          <span className="environment-badge">
            <span className="live-dot" />
            {t("UI lab", "مختبر الواجهة")}
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
            onClick={() => setNotifications(true)}
          >
            <Bell size={16} />
          </Button>
        </div>
      </header>
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
            placeholder="SHP-10482, barcode, Dammam…"
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
                  <b>{c.id}</b>
                  <small>
                    {c.issue} · {c.shipment.destination}
                  </small>
                </span>
                <StatusBadge status={c.status} />
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
              {t(
                "Recent events from the local simulation.",
                "أحداث حديثة من المحاكاة المحلية.",
              )}
            </SheetDescription>
          </SheetHeader>
          <div className="sheet-body">
            {[...events]
              .sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp))
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
                      {e.caseId} · {timeLabel(e.timestamp)} ·{" "}
                      {t("simulated", "محاكاة")}
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
  const resolved = cases
    .filter((c) => c.status === "resolved")
    .map((c) => c.id);
  const previous = useRef(new Set(resolved));
  const [recent, setRecent] = useState<string | null>(null);
  useEffect(() => {
    const next = cases.filter((c) => c.status === "resolved").map((c) => c.id);
    const added = next.find((id) => !previous.current.has(id));
    previous.current = new Set(next);
    if (added) setRecent(added);
  }, [cases]);
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
            {t(
              "Synthetic data · local simulation",
              "بيانات اصطناعية · محاكاة محلية",
            )}
            <span>·</span> 09 OCT 2026
          </span>
        </footer>
      </div>
      <ResolutionTransfer />
      <OperationalNotifications />
    </SidebarProvider>
  );
}
