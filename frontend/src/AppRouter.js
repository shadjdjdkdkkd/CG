import React, { useEffect, lazy, Suspense, useState } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { loadNicheBrands } from './utils/brand';
import ScrollToTop from './components/ScrollToTop';
import { TrackingProvider } from './providers/TrackingProvider';
import PublicLayout from './layouts/PublicLayout';
import AdminMobileNav, { AdminDesktopSidebar } from './components/admin/AdminMobileNav';
import SplashScreen from './components/SplashScreen';

// Eagerly loaded pages (critical for first paint)
import Homepage from './pages/Homepage';
import DelayedLoader from './components/DelayedLoader';

// Lazy loaded public pages
const ProductDetailPage = lazy(() => import('./pages/ProductDetailPage'));
const ShopPage = lazy(() => import('./pages/ShopPage'));
const CartPage = lazy(() => import('./pages/CartPage'));
const CheckoutPage = lazy(() => import('./pages/CheckoutPage'));
const ConcernCategoryPage = lazy(() => import('./pages/ConcernCategoryPage'));
const CustomizeProductPage = lazy(() => import('./pages/CustomizeProductPage'));
const CertificatesPage = lazy(() => import('./pages/CertificatesPage'));
const SkincareHome = lazy(() => import('./pages/SkincareHome'));
const CosmeticsHome = lazy(() => import('./pages/CosmeticsHome'));
const CategoriesPage = lazy(() => import('./pages/CategoriesPage'));
const BrandsListingPage = lazy(() => import('./pages/BrandsListingPage'));
const BrandDetailPage = lazy(() => import('./pages/BrandDetailPage'));
const RoutinePage = lazy(() => import('./pages/RoutinePage'));
const JourneyPage = lazy(() => import('./pages/JourneyPage'));
const TrackerPage = lazy(() => import('./pages/TrackerPage'));
const AccountPage = lazy(() => import('./pages/AccountPage'));

// Lazy loaded public pages (loaded on demand)
const OrderSuccessPage = lazy(() => import('./pages/OrderSuccessPage'));
const BlogList = lazy(() => import('./pages/BlogList'));
const BlogPost = lazy(() => import('./pages/BlogPost'));
const LocationPage = lazy(() => import('./pages/LocationPage'));
const SearchResults = lazy(() => import('./pages/SearchResults'));
const ConsultationPage = lazy(() => import('./pages/ConsultationPage'));
const DoctorConsultationPage = lazy(() => import('./pages/DoctorConsultationPage'));
const LeadFormPage = lazy(() => import('./pages/LeadFormPage'));
const SalePage = lazy(() => import('./pages/SalePage'));
const TermsPage = lazy(() => import('./pages/TermsPage'));
const PrivacyPage = lazy(() => import('./pages/PrivacyPage'));
const TrackOrder = lazy(() => import('./pages/TrackOrder'));
const ContactPage = lazy(() => import('./pages/ContactPage'));
const AboutPage = lazy(() => import('./pages/AboutPage'));
const RefundPolicyPage = lazy(() => import('./pages/RefundPolicyPage'));
const ShippingPolicyPage = lazy(() => import('./pages/ShippingPolicyPage'));

// Lazy loaded admin pages (separate chunk, only loaded when visiting admin)
const AdminLogin = lazy(() => import('./pages/admin/AdminLogin'));
const AdminDashboard = lazy(() => import('./pages/admin/AdminDashboard'));
const AdminBlogs = lazy(() => import('./pages/admin/AdminBlogs'));
const AdminBlogEditor = lazy(() => import('./pages/admin/AdminBlogEditor'));
const AdminLocations = lazy(() => import('./pages/admin/AdminLocations'));
const AdminLocationEditor = lazy(() => import('./pages/admin/AdminLocationEditor'));
const AdminOrders = lazy(() => import('./pages/admin/AdminOrders'));
const AdminDeliveryMen = lazy(() => import('./pages/admin/AdminDeliveryMen'));
const AdminWarehouses = lazy(() => import('./pages/admin/AdminWarehouses'));
const AdminOffers = lazy(() => import('./pages/admin/AdminOffers'));
const AdminMediaTools = lazy(() => import('./pages/admin/AdminMediaTools'));
const AdminReels = lazy(() => import('./pages/admin/AdminReels'));
const AdminAIStudio = lazy(() => import('./pages/admin/AdminAIStudio'));
const AdminTrendProducts = lazy(() => import('./pages/admin/AdminTrendProducts'));
const AdminImageGallery = lazy(() => import('./pages/admin/AdminImageGallery'));
const AdminConsultations = lazy(() => import('./pages/admin/AdminConsultations'));
const AdminDoctorBookings = lazy(() => import('./pages/admin/AdminDoctorBookings'));
const AdminMarketplace = lazy(() => import('./pages/admin/AdminMarketplace'));
const AdminServices = lazy(() => import('./pages/admin/AdminServices'));
const AdminMpCRM = lazy(() => import('./pages/admin/AdminMpCRM'));
const AdminMpBookings = lazy(() => import('./pages/admin/AdminMpBookings'));
const AdminSupport = lazy(() => import('./pages/admin/AdminSupport'));
const AdminDoctorHub = lazy(() => import('./pages/admin/AdminDoctorHub'));
const AdminPartnerHub = lazy(() => import('./pages/admin/AdminPartnerHub'));
const MpDoctorsPage = lazy(() => import('./pages/mp/DoctorsPage'));
const MpDoctorProfilePage = lazy(() => import('./pages/mp/DoctorProfilePage'));
const MpServicesPage = lazy(() => import('./pages/mp/ServicesPage'));
const MpServiceDetailPage = lazy(() => import('./pages/mp/ServiceDetailPage'));
const HbCategoryPage = lazy(() => import('./pages/mp/HbCategoryPage'));
const MpTrackingPage = lazy(() => import('./pages/mp/TrackingPage'));
const MpConsultRoomPage = lazy(() => import('./pages/mp/ConsultRoomPage'));
const MpDoctorApplyPage = lazy(() => import('./pages/mp/DoctorApplyPage'));
const MpPartnerApplyPage = lazy(() => import('./pages/mp/PartnerApplyPage'));
const MpDoctorPortalPage = lazy(() => import('./pages/mp/DoctorPortalPage'));
const MpPartnerPortalPage = lazy(() => import('./pages/mp/PartnerPortalPage'));
const MpSupportPage = lazy(() => import('./pages/mp/SupportPage'));
const MpProviderApp = lazy(() => import('./pages/mp/ProviderApp'));
const AdminExtras = lazy(() => import('./pages/admin/AdminExtras'));
const AdminUserJourney = lazy(() => import('./pages/admin/AdminUserJourney'));
const AdminLiveVisitors = lazy(() => import('./pages/admin/AdminLiveVisitors'));
const AdminWhatsApp = lazy(() => import('./pages/admin/AdminWhatsApp'));
const AdminReferrals = lazy(() => import('./pages/admin/AdminReferrals'));
const AdminLandingPages = lazy(() => import('./pages/admin/AdminLandingPages'));
const AdminEmployees = lazy(() => import('./pages/admin/AdminEmployees'));
const AdminCustomers = lazy(() => import('./pages/admin/AdminCustomers'));
const AdminProducts = lazy(() => import('./pages/admin/AdminProducts'));
const AdminConcerns = lazy(() => import('./pages/admin/AdminConcerns'));
const AmazonFlipkartListing = lazy(() => import('./pages/admin/AmazonFlipkartListing'));
const AfDashboardApp = lazy(() => import('./af/App'));
const AdminNiches = lazy(() => import('./pages/admin/AdminNiches'));
const AdminCategoriesHub = lazy(() => import('./pages/admin/AdminCategoriesHub'));
const AdminMissingImages = lazy(() => import('./pages/admin/AdminMissingImages'));
const AdminRetention = lazy(() => import('./pages/admin/AdminRetention'));
const AdminReviews = lazy(() => import('./pages/admin/AdminReviews'));
const AdminSettings = lazy(() => import('./pages/admin/AdminSettings'));
const AdminRoutines = lazy(() => import('./pages/admin/AdminRoutines'));
const AdminTrackers = lazy(() => import('./pages/admin/AdminTrackers'));
const AdminBulkImport = lazy(() => import('./pages/admin/AdminBulkImport'));
const AdminMasterTools = lazy(() => import('./pages/admin/AdminMasterTools'));
const AdminGiftCards = lazy(() => import('./pages/admin/AdminGiftCards'));
const AdminBrands = lazy(() => import('./pages/admin/AdminBrands'));

// Employee Pages
const EmployeeLogin = lazy(() => import('./pages/employee/EmployeeLogin'));
const EmployeeDashboard = lazy(() => import('./pages/employee/EmployeeDashboard'));
const EmployeeLayout = lazy(() => import('./layouts/EmployeeLayout'));
const EmployeeOrders = lazy(() => import('./pages/employee/EmployeeOrders'));
const EmployeeCustomers = lazy(() => import('./pages/employee/EmployeeCustomers'));
const EmployeeBlogs = lazy(() => import('./pages/employee/EmployeeBlogs'));
const EmployeeAnalytics = lazy(() => import('./pages/employee/EmployeeAnalytics'));
const EmployeeLandingPages = lazy(() => import('./pages/employee/EmployeeLandingPages'));
const EmployeeConsultations = lazy(() => import('./pages/employee/EmployeeConsultations'));
const EmployeeProducts = lazy(() => import('./pages/employee/EmployeeProducts'));
const EmployeeRetention = lazy(() => import('./pages/employee/EmployeeRetention'));

// Landing Page Funnel removed (per user request)

// Legacy Landing Page (for backward compatibility with /lp/ URLs)
const LandingPage = lazy(() => import('./pages/LandingPage'));

// Loading spinner for lazy loaded pages (delayed — only appears for slow chunk loads)
const PageLoader = () => <DelayedLoader delay={280} />;

// Admin layout wrapper — enforces auth before rendering any child admin page.
// Previously each admin page relied on its own `useAdminAuth` check, which
// meant a page with a slow-loading component (or one that forgot the check)
// could momentarily reveal admin content before redirecting. This wrapper
// short-circuits the render tree the moment we know there's no token.
const AdminLayout = ({ children }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const isLoginRoute = location.pathname === '/admin' || location.pathname === '/admin/login';
  const hasToken = typeof window !== 'undefined' && (
    sessionStorage.getItem('adminToken') || localStorage.getItem('adminToken')
  );
  useEffect(() => {
    if (!isLoginRoute && !hasToken) navigate('/admin', { replace: true });
  }, [isLoginRoute, hasToken, navigate]);
  if (!isLoginRoute && !hasToken) {
    return <div className="min-h-screen bg-stone-50 flex items-center justify-center"><PageLoader /></div>;
  }
  return (
    <Suspense fallback={<PageLoader />}>
      <AdminMobileNav />
      <AdminDesktopSidebar />
      <div data-admin-content="">{children}</div>
    </Suspense>
  );
};

function App() {
  // SplashScreen mounts once per browser session; it stays out of the way on
  // intra-tab navigation so the rest of the app is unaffected.
  const [splashGone, setSplashGone] = useState(false);
  const isAdminRoute = typeof window !== 'undefined' && window.location.pathname.startsWith('/admin');
  // Don't show splash on admin / employee paths
  const showSplash = !splashGone && !isAdminRoute;

  useEffect(() => {
    // Detect referral code from URL on any page load and store in sessionStorage
    const urlParams = new URLSearchParams(window.location.search);
    const refCode = urlParams.get('ref');
    if (refCode) {
      sessionStorage.setItem('referralCode', refCode);
      console.log('[Referral] Code detected in URL:', refCode);
    }
    // Warm per-niche brand cache so ProductCard renders the right brand on first paint
    loadNicheBrands();

    // PERF: Keep-alive ping. The Emergent prod pod scales to zero after idle,
    // causing a 5-30s cold-start on the next request. A tiny /api/health ping
    // every 4 minutes while the tab is open keeps the pod warm. Cost: ~30 bytes
    // every 4 min. Benefit: search/niche-switch never hits cold-start again.
    const API = process.env.REACT_APP_BACKEND_URL;
    let pingTimer = null;
    let lastPingAt = 0;
    const ping = () => {
      if (document.visibilityState !== 'visible') return;
      // Throttle: don't ping more than once every 60s to avoid spamming on rapid tab-flicker
      if (Date.now() - lastPingAt < 60_000) return;
      lastPingAt = Date.now();
      try { fetch(`${API}/api/health`, { credentials: 'omit', cache: 'no-store' }).catch(() => {}); } catch (_) {}
    };
    ping();
    pingTimer = setInterval(ping, 4 * 60 * 1000);
    document.addEventListener('visibilitychange', ping);
    return () => {
      if (pingTimer) clearInterval(pingTimer);
      document.removeEventListener('visibilitychange', ping);
    };
  }, []);

  return (
    <Router>
      {showSplash && <SplashScreen onDone={() => setSplashGone(true)} />}
      <ScrollToTop />
      <Routes>
        {/* Admin Routes - No tracking provider, lazy loaded */}
        <Route path="/admin" element={<AdminLayout><AdminLogin /></AdminLayout>} />
        <Route path="/admin/dashboard" element={<AdminLayout><AdminDashboard /></AdminLayout>} />
        <Route path="/admin/blogs" element={<AdminLayout><AdminBlogs /></AdminLayout>} />
        <Route path="/admin/blogs/new" element={<AdminLayout><AdminBlogEditor /></AdminLayout>} />
        <Route path="/admin/blogs/edit/:id" element={<AdminLayout><AdminBlogEditor /></AdminLayout>} />
        <Route path="/admin/locations" element={<AdminLayout><AdminLocations /></AdminLayout>} />
        <Route path="/admin/locations/new" element={<AdminLayout><AdminLocationEditor /></AdminLayout>} />
        <Route path="/admin/locations/edit/:id" element={<AdminLayout><AdminLocationEditor /></AdminLayout>} />
        <Route path="/admin/orders" element={<AdminLayout><AdminOrders /></AdminLayout>} />
        <Route path="/admin/delivery-men" element={<AdminLayout><AdminDeliveryMen /></AdminLayout>} />
        <Route path="/admin/warehouses" element={<AdminLayout><AdminWarehouses /></AdminLayout>} />
        <Route path="/admin/offers" element={<AdminLayout><AdminOffers /></AdminLayout>} />
        <Route path="/admin/media-tools" element={<AdminLayout><AdminMediaTools /></AdminLayout>} />
        <Route path="/admin/reels" element={<AdminLayout><AdminReels /></AdminLayout>} />
        <Route path="/admin/ai-studio" element={<AdminLayout><AdminAIStudio /></AdminLayout>} />
        <Route path="/admin/trend-products" element={<AdminLayout><AdminTrendProducts /></AdminLayout>} />
        <Route path="/admin/image-gallery" element={<AdminLayout><AdminImageGallery /></AdminLayout>} />
        <Route path="/admin/consultations" element={<AdminLayout><AdminConsultations /></AdminLayout>} />
        <Route path="/admin/doctor-bookings" element={<AdminLayout><AdminDoctorBookings /></AdminLayout>} />
        <Route path="/admin/marketplace" element={<AdminLayout><AdminMarketplace /></AdminLayout>} />
        <Route path="/admin/services-catalogue" element={<AdminLayout><AdminServices /></AdminLayout>} />
        <Route path="/admin/doctors-crm" element={<AdminLayout><AdminMpCRM kind="doctors" /></AdminLayout>} />
        <Route path="/admin/partners-crm" element={<AdminLayout><AdminMpCRM kind="partners" /></AdminLayout>} />
        <Route path="/admin/marketplace-bookings" element={<AdminLayout><AdminMpBookings /></AdminLayout>} />
        <Route path="/admin/support" element={<AdminLayout><AdminSupport /></AdminLayout>} />
        <Route path="/admin/dermatologists" element={<AdminLayout><AdminDoctorHub /></AdminLayout>} />
        <Route path="/admin/partners" element={<AdminLayout><AdminPartnerHub /></AdminLayout>} />
        <Route path="/admin/extras" element={<AdminLayout><AdminExtras /></AdminLayout>} />
        <Route path="/admin/user-journey" element={<AdminLayout><AdminUserJourney /></AdminLayout>} />
        <Route path="/admin/live-visitors" element={<AdminLayout><AdminLiveVisitors /></AdminLayout>} />
        <Route path="/admin/whatsapp" element={<AdminLayout><AdminWhatsApp /></AdminLayout>} />
        <Route path="/admin/referrals" element={<AdminLayout><AdminReferrals /></AdminLayout>} />
        <Route path="/admin/landing-pages" element={<AdminLayout><AdminLandingPages /></AdminLayout>} />
        <Route path="/admin/employees" element={<AdminLayout><AdminEmployees /></AdminLayout>} />
        <Route path="/admin/customers" element={<AdminLayout><AdminCustomers /></AdminLayout>} />
        <Route path="/admin/products" element={<AdminLayout><AdminProducts /></AdminLayout>} />
        <Route path="/admin/concerns" element={<AdminLayout><AdminConcerns /></AdminLayout>} />
        <Route path="/admin/amazon-flipkart" element={<AdminLayout><AmazonFlipkartListing /></AdminLayout>} />
        <Route path="/admin/categories" element={<AdminLayout><AdminConcerns /></AdminLayout>} />
        <Route path="/admin/niches" element={<AdminLayout><AdminNiches /></AdminLayout>} />
        <Route path="/admin/categories-hub" element={<AdminLayout><AdminCategoriesHub /></AdminLayout>} />
        <Route path="/admin/missing-images" element={<AdminLayout><AdminMissingImages /></AdminLayout>} />
        <Route path="/admin/retention" element={<AdminLayout><AdminRetention /></AdminLayout>} />
        <Route path="/admin/reviews" element={<AdminLayout><AdminReviews /></AdminLayout>} />
        <Route path="/admin/settings" element={<AdminLayout><AdminSettings /></AdminLayout>} />
        <Route path="/admin/routines" element={<AdminLayout><AdminRoutines /></AdminLayout>} />
        <Route path="/admin/trackers" element={<AdminLayout><AdminTrackers /></AdminLayout>} />
        <Route path="/admin/bulk-import" element={<AdminLayout><AdminBulkImport /></AdminLayout>} />
        <Route path="/admin/master-tools" element={<AdminLayout><AdminMasterTools /></AdminLayout>} />
        <Route path="/admin/gift-cards" element={<AdminLayout><AdminGiftCards /></AdminLayout>} />
        <Route path="/admin/brands" element={<AdminLayout><AdminBrands /></AdminLayout>} />
        
        {/* Employee Routes */}
        <Route path="/employee/login" element={
          <Suspense fallback={<PageLoader />}><EmployeeLogin /></Suspense>
        } />
        <Route path="/employee/dashboard" element={
          <Suspense fallback={<PageLoader />}><EmployeeDashboard /></Suspense>
        } />
        <Route path="/employee/orders" element={
          <Suspense fallback={<PageLoader />}>
            <EmployeeLayout requiredPermission="orders"><EmployeeOrders /></EmployeeLayout>
          </Suspense>
        } />
        <Route path="/employee/customers" element={
          <Suspense fallback={<PageLoader />}>
            <EmployeeLayout requiredPermission="customers"><EmployeeCustomers /></EmployeeLayout>
          </Suspense>
        } />
        <Route path="/employee/blogs" element={
          <Suspense fallback={<PageLoader />}>
            <EmployeeLayout requiredPermission="blogs"><EmployeeBlogs /></EmployeeLayout>
          </Suspense>
        } />
        <Route path="/employee/analytics" element={
          <Suspense fallback={<PageLoader />}>
            <EmployeeLayout requiredPermission="analytics"><EmployeeAnalytics /></EmployeeLayout>
          </Suspense>
        } />
        <Route path="/employee/landing-pages" element={
          <Suspense fallback={<PageLoader />}>
            <EmployeeLayout requiredPermission="landing_pages"><EmployeeLandingPages /></EmployeeLayout>
          </Suspense>
        } />
        <Route path="/employee/consultations" element={
          <Suspense fallback={<PageLoader />}>
            <EmployeeLayout requiredPermission="consultations"><EmployeeConsultations /></EmployeeLayout>
          </Suspense>
        } />
        <Route path="/employee/products" element={
          <Suspense fallback={<PageLoader />}>
            <EmployeeLayout requiredPermission="products"><EmployeeProducts /></EmployeeLayout>
          </Suspense>
        } />
        <Route path="/employee/retention" element={
          <Suspense fallback={<PageLoader />}>
            <EmployeeLayout requiredPermission="retention"><EmployeeRetention /></EmployeeLayout>
          </Suspense>
        } />
        <Route path="/employee/*" element={
          <Suspense fallback={<PageLoader />}><EmployeeDashboard /></Suspense>
        } />
        
        {/* Public Routes - With tracking provider */}
        <Route path="/*" element={
          <TrackingProvider>
            <Routes>
              {/* Consultation Route (full screen, no navigation) */}
              <Route path="/consultation" element={
                <Suspense fallback={<PageLoader />}>
                  <ConsultationPage />
                </Suspense>
              } />
              <Route path="/doctor-consultation" element={
                <PublicLayout>
                  <Suspense fallback={<PageLoader />}><DoctorConsultationPage /></Suspense>
                </PublicLayout>
              } />
              {/* Marketplace: dermatologist consultations & home services */}
              <Route path="/doctors" element={<PublicLayout><Suspense fallback={<PageLoader />}><MpDoctorsPage /></Suspense></PublicLayout>} />
              <Route path="/doctors/:doctorId" element={<PublicLayout><Suspense fallback={<PageLoader />}><MpDoctorProfilePage /></Suspense></PublicLayout>} />
              <Route path="/services" element={<PublicLayout><Suspense fallback={<PageLoader />}><MpServicesPage /></Suspense></PublicLayout>} />
              <Route path="/services/:serviceId" element={<PublicLayout><Suspense fallback={<PageLoader />}><MpServiceDetailPage /></Suspense></PublicLayout>} />
              <Route path="/my/bookings" element={<Navigate to="/account?tab=bookings" replace />} />
              <Route path="/services/category/:catId" element={<PublicLayout><Suspense fallback={<PageLoader />}><HbCategoryPage /></Suspense></PublicLayout>} />
              <Route path="/track/:bookingId" element={<PublicLayout><Suspense fallback={<PageLoader />}><MpTrackingPage /></Suspense></PublicLayout>} />
              <Route path="/doctor/apply" element={<PublicLayout><Suspense fallback={<PageLoader />}><MpDoctorApplyPage /></Suspense></PublicLayout>} />
              <Route path="/partner/apply" element={<PublicLayout><Suspense fallback={<PageLoader />}><MpPartnerApplyPage /></Suspense></PublicLayout>} />
              <Route path="/doctor" element={<Suspense fallback={<PageLoader />}><MpDoctorPortalPage /></Suspense>} />
              <Route path="/partner" element={<Suspense fallback={<PageLoader />}><MpPartnerPortalPage /></Suspense>} />
              <Route path="/pro" element={<Suspense fallback={<PageLoader />}><MpProviderApp /></Suspense>} />
              <Route path="/support" element={<PublicLayout><Suspense fallback={<PageLoader />}><MpSupportPage /></Suspense></PublicLayout>} />
              <Route path="/consult-room/:bookingId" element={<Suspense fallback={<PageLoader />}><MpConsultRoomPage /></Suspense>} />
              <Route path="/sale/:slug" element={<PublicLayout><Suspense fallback={<PageLoader />}><SalePage /></Suspense></PublicLayout>} />
              
              {/* Legal Pages */}
              <Route path="/terms" element={
                <PublicLayout>
                  <Suspense fallback={<PageLoader />}><TermsPage /></Suspense>
                </PublicLayout>
              } />
              <Route path="/privacy" element={
                <PublicLayout>
                  <Suspense fallback={<PageLoader />}><PrivacyPage /></Suspense>
                </PublicLayout>
              } />
              <Route path="/refund-policy" element={
                <PublicLayout>
                  <Suspense fallback={<PageLoader />}><RefundPolicyPage /></Suspense>
                </PublicLayout>
              } />
              <Route path="/shipping-policy" element={
                <PublicLayout>
                  <Suspense fallback={<PageLoader />}><ShippingPolicyPage /></Suspense>
                </PublicLayout>
              } />
              <Route path="/contact" element={
                <PublicLayout>
                  <Suspense fallback={<PageLoader />}><ContactPage /></Suspense>
                </PublicLayout>
              } />
              <Route path="/about" element={
                <PublicLayout>
                  <Suspense fallback={<PageLoader />}><AboutPage /></Suspense>
                </PublicLayout>
              } />
              
              {/* Legacy Landing Pages (backward compatibility with /lp/ URLs) */}
              <Route path="/lp/:slug" element={
                <Suspense fallback={<PageLoader />}>
                  <LandingPage />
                </Suspense>
              } />
              
              {/* Track Order Page */}
              <Route path="/track-order" element={
                <Suspense fallback={<PageLoader />}><TrackOrder /></Suspense>
              } />
              
              {/* Main Public Routes */}
              <Route path="/" element={<PublicLayout><Homepage /></PublicLayout>} />
              <Route path="/shop" element={
                <PublicLayout><Suspense fallback={<PageLoader />}><ShopPage /></Suspense></PublicLayout>
              } />
              <Route path="/skincare" element={
                <PublicLayout><Suspense fallback={<PageLoader />}><SkincareHome /></Suspense></PublicLayout>
              } />
              <Route path="/cosmetics" element={
                <PublicLayout><Suspense fallback={<PageLoader />}><CosmeticsHome /></Suspense></PublicLayout>
              } />
              <Route path="/categories" element={
                <PublicLayout><Suspense fallback={<PageLoader />}><CategoriesPage /></Suspense></PublicLayout>
              } />
              <Route path="/routine" element={
                <PublicLayout><Suspense fallback={<PageLoader />}><RoutinePage /></Suspense></PublicLayout>
              } />
              <Route path="/journey/:jid" element={
                <PublicLayout><Suspense fallback={<PageLoader />}><JourneyPage /></Suspense></PublicLayout>
              } />
              <Route path="/account" element={
                <PublicLayout><Suspense fallback={<PageLoader />}><TrackerPage /></Suspense></PublicLayout>
              } />
              <Route path="/tracker" element={
                <PublicLayout><Suspense fallback={<PageLoader />}><TrackerPage /></Suspense></PublicLayout>
              } />
              {/* Concern & category filtered pages (restored) — show ONLY products for the tapped concern/type */}
              <Route path="/concern/:slug" element={
                <PublicLayout><Suspense fallback={<PageLoader />}><ConcernCategoryPage mode="concern" /></Suspense></PublicLayout>
              } />
              <Route path="/category/:slug" element={
                <PublicLayout><Suspense fallback={<PageLoader />}><ConcernCategoryPage mode="category" /></Suspense></PublicLayout>
              } />
              {/* Choose Your Customized Product — all 24 variations of a product group */}
              <Route path="/customize/:slug" element={
                <PublicLayout><Suspense fallback={<PageLoader />}><CustomizeProductPage /></Suspense></PublicLayout>
              } />
              <Route path="/certificates" element={
                <PublicLayout><Suspense fallback={<PageLoader />}><CertificatesPage /></Suspense></PublicLayout>
              } />
              <Route path="/brands" element={
                <PublicLayout><Suspense fallback={<PageLoader />}><BrandsListingPage /></Suspense></PublicLayout>
              } />
              <Route path="/brands/:slug" element={
                <PublicLayout><Suspense fallback={<PageLoader />}><BrandDetailPage /></Suspense></PublicLayout>
              } />
              <Route path="/product/:slug" element={
                <PublicLayout><Suspense fallback={<PageLoader />}><ProductDetailPage /></Suspense></PublicLayout>
              } />
              <Route path="/cart" element={
                <PublicLayout><Suspense fallback={<PageLoader />}><CartPage /></Suspense></PublicLayout>
              } />
              <Route path="/checkout" element={
                <PublicLayout><Suspense fallback={<PageLoader />}><CheckoutPage /></Suspense></PublicLayout>
              } />
              <Route path="/order-success/:orderId" element={
                <PublicLayout>
                  <Suspense fallback={<PageLoader />}><OrderSuccessPage /></Suspense>
                </PublicLayout>
              } />
              <Route path="/blog" element={
                <PublicLayout>
                  <Suspense fallback={<PageLoader />}><BlogList /></Suspense>
                </PublicLayout>
              } />
              <Route path="/blog/:slug" element={
                <PublicLayout>
                  <Suspense fallback={<PageLoader />}><BlogPost /></Suspense>
                </PublicLayout>
              } />
              <Route path="/search" element={
                <PublicLayout>
                  <Suspense fallback={<PageLoader />}><SearchResults /></Suspense>
                </PublicLayout>
              } />

              {/* Public lead-capture pages — mobile-friendly single-column forms.
                  Component (LeadFormPage.js) auto-detects the type from the URL. */}
              <Route path="/investor" element={
                <PublicLayout>
                  <Suspense fallback={<PageLoader />}><LeadFormPage type="invest" /></Suspense>
                </PublicLayout>
              } />
              <Route path="/invest" element={
                <PublicLayout>
                  <Suspense fallback={<PageLoader />}><LeadFormPage type="invest" /></Suspense>
                </PublicLayout>
              } />
              <Route path="/skin-issue" element={
                <PublicLayout>
                  <Suspense fallback={<PageLoader />}><LeadFormPage type="skin_concern" /></Suspense>
                </PublicLayout>
              } />
              <Route path="/skin-advice" element={
                <PublicLayout>
                  <Suspense fallback={<PageLoader />}><LeadFormPage type="skin_concern" /></Suspense>
                </PublicLayout>
              } />
              <Route path="/partner" element={
                <PublicLayout>
                  <Suspense fallback={<PageLoader />}><LeadFormPage type="partner" /></Suspense>
                </PublicLayout>
              } />

              {/* Catch-all 404 — prevents white-screen on bad CTAs / stale links.
                  Falls back to the homepage with a soft message instead of a blank page. */}
              <Route path="*" element={
                <PublicLayout>
                  <div className="min-h-[60vh] flex items-center justify-center px-6 text-center" data-testid="page-not-found">
                    <div>
                      <h1 className="text-5xl font-light text-stone-900 mb-3">404</h1>
                      <p className="text-stone-600 mb-6">This page doesn't exist or has moved.</p>
                      <a href="/" className="inline-flex items-center gap-2 px-6 py-3 rounded-full bg-green-700 text-white font-semibold text-sm hover:bg-green-800 transition">Back to home</a>
                    </div>
                  </div>
                </PublicLayout>
              } />

              {/* Landing Page Funnel route removed — was matching every unmatched
                  path and conflicting with real routes. */}
            </Routes>
          </TrackingProvider>
        } />
      </Routes>
    </Router>
  );
}

export default App;
