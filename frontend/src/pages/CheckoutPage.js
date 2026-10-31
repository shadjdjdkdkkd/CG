import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import axios from 'axios';
import { Shield, Truck, ArrowLeft, Check, MapPin, Clock, Star, Award, Gift, Lock, Users, Package } from 'lucide-react';
import { getCart, saveCart, addToCart } from './Homepage';
import { useTracking } from '../providers/TrackingProvider';
import CheckoutMap from '../components/CheckoutMap';
import CheckoutSurpriseModal from '../components/CheckoutSurpriseModal';
import { getSessionId } from '../utils/userTracking';

const STORED_LOCATION_KEY = 'cg_delivery_location';

const API = process.env.REACT_APP_BACKEND_URL;

// Small cookie reader — used to lift the Facebook browser cookies (`_fbp`,
// `_fbc`) so we can forward them to the server-side CAPI Purchase event.
const getCookie = (name) => {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.split('; ').find((r) => r.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split('=').slice(1).join('=')) : null;
};

// Defined at module scope so React doesn't remount the <input> on every keystroke
// (which was causing the mobile keyboard to auto-dismiss after each character).
const Field = React.memo(function Field({ label, field, type = 'text', placeholder, span, value, error, onChange, inputMode }) {
  return (
    <div className={span ? 'sm:col-span-2' : ''}>
      <label className="block text-xs font-bold text-gray-400 uppercase tracking-wider mb-1.5">{label}</label>
      <input
        type={type}
        inputMode={inputMode}
        value={value || ''}
        onChange={e => onChange(field, e.target.value)}
        placeholder={placeholder}
        className={`w-full px-4 py-3 border rounded-xl text-sm bg-stone-50 focus:bg-white focus:ring-2 focus:ring-green-200 transition-all outline-none ${error ? 'border-red-300' : 'border-gray-200'}`}
        data-testid={`checkout-${field}`}
        autoComplete={field === 'name' ? 'name' : field === 'phone' ? 'tel' : field === 'email' ? 'email' : field === 'pincode' ? 'postal-code' : field === 'city' ? 'address-level2' : field === 'state' ? 'address-level1' : field === 'area' ? 'street-address' : 'on'}
      />
      {error && <p className="text-red-500 text-xs mt-1">{error}</p>}
    </div>
  );
});

function CheckoutPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { trackAction, trackGAEvent } = useTracking();
  const { cartData: passedCartData, paymentMethod: passedMethod, coupon, giftCard } = location.state || {};
  const [cartData, setCartData] = useState(() => {
    // PERF: hydrate instantly from sessionStorage so the checkout renders in
    // one paint. The live re-validate below still runs on mount so any stale
    // price/stock is corrected within a network round-trip.
    if (passedCartData) return passedCartData;
    try {
      const cached = sessionStorage.getItem('cg_checkout_cart_v1');
      if (cached) {
        const j = JSON.parse(cached);
        if (j && j.__at && Date.now() - j.__at < 5 * 60 * 1000) return j;
      }
    } catch (_) {}
    return null;
  });
  const [paymentMethod, setPaymentMethod] = useState(passedMethod || 'prepaid');
  // ₹100 OFF Prepaid Bonus — opt-in toggle. When ON, we force paymentMethod
  // to 'prepaid' + pass `prepaid_bonus:true` to /api/cart/validate. Backend
  // enforces the same rule so COD orders can never claim the bonus.
  const [prepaidBonus, setPrepaidBonus] = useState(false);

  // ---- Flash Offer Timer (3 min urgency, 2 day cooldown) ----
  // On first checkout visit we stamp `startedAt` in localStorage. During the
  // 3-min window the anti-aging perks + prepaid bonus + zero tax/delivery are
  // ALL available. After 3 min they lock. After 2 days the timer auto-resets.
  const PROMO_KEY = 'cg_promo_offer_v1';
  const PROMO_WINDOW_MS = 10 * 60 * 1000;        // 10 minutes
  const PROMO_COOLDOWN_MS = 2 * 24 * 60 * 60 * 1000; // 2 days
  const readPromoState = () => {
    try {
      const raw = localStorage.getItem(PROMO_KEY);
      const j = raw ? JSON.parse(raw) : null;
      const now = Date.now();
      if (!j || !j.startedAt) return { startedAt: now, fresh: true };
      // 2-day cooldown reset — treat as brand-new window
      if (now - j.startedAt >= PROMO_COOLDOWN_MS) return { startedAt: now, fresh: true };
      return { startedAt: j.startedAt, fresh: false };
    } catch (_) { return { startedAt: Date.now(), fresh: true }; }
  };
  const [promoStartedAt] = useState(() => {
    const s = readPromoState();
    if (s.fresh) {
      try { localStorage.setItem(PROMO_KEY, JSON.stringify({ startedAt: s.startedAt })); } catch (_) {}
    }
    return s.startedAt;
  });
  const [nowTs, setNowTs] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNowTs(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  const promoExpiresAt = promoStartedAt + PROMO_WINDOW_MS;
  const promoRemainingMs = Math.max(0, promoExpiresAt - nowTs);
  const promoActive = promoRemainingMs > 0;
  const promoMinutes = Math.floor(promoRemainingMs / 60000);
  const promoSeconds = Math.floor((promoRemainingMs % 60000) / 1000);
  // Time until offer reactivates (after 3-min lock + 2-day cooldown from start)
  const promoReactivateAt = promoStartedAt + PROMO_COOLDOWN_MS;
  const hoursUntilReactivate = Math.max(0, Math.ceil((promoReactivateAt - nowTs) / (60 * 60 * 1000)));
  // Payment policy — admin toggles COD restriction from /admin/offers. When
  // the flag is off (default), COD works exactly like before. When on, COD is
  // gated to Celesta Glow's own anti-aging products OR instant-delivery zones.
  const [codRestrictionEnabled, setCodRestrictionEnabled] = useState(false);
  // Store-wide "prepaid only" master switch (admin dashboard). When ON, COD is
  // fully disabled regardless of niche / pincode.
  const [prepaidOnly, setPrepaidOnly] = useState(false);
  useEffect(() => {
    axios.get(`${API}/api/payment-policy`)
      .then((r) => setCodRestrictionEnabled(!!r.data?.cod_restriction_enabled))
      .catch(() => setCodRestrictionEnabled(false));
    axios.get(`${API}/api/site-settings`)
      .then((r) => setPrepaidOnly(!!r.data?.prepaid_only))
      .catch(() => setPrepaidOnly(false));
  }, []);

  // COD availability gate (Feb 2026 policy):
  //   • Toggle OFF (default) → COD always allowed
  //   • Toggle ON:
  //       • Celesta Glow's own products (anti-aging niche) → COD + Prepaid
  //       • Third-party niches (skincare / cosmetics) → Prepaid only
  //       • EXCEPT when the customer's saved pincode is within warehouse coverage
  //         (instant delivery available) → COD unlocked for ANY item.
  //   The pincode-based zone check (Feb-2026) fills the gap where the user
  //   didn't give browser geolocation — we resolve pincode → coords server-side
  //   and OR the result into `pincodeInZone` above.
  // NOTE: pincodeInZone useState is declared HERE (above the useMemo) so we
  // don't hit a temporal-dead-zone crash when React evaluates the memo.
  const [pincodeInZone, setPincodeInZone] = useState(null); // null=unknown, true=in-zone, false=out-of-zone
  const codAvailable = React.useMemo(() => {
    if (prepaidOnly) return false; // store-wide prepaid-only master switch
    if (!codRestrictionEnabled) return true; // policy off → legacy behaviour
    const items = cartData?.items || [];
    if (items.length === 0) return true;
    const niches = new Set(items.map((it) => String(it.niche || '').toLowerCase()));
    const allAntiAging = niches.size > 0 && [...niches].every((n) => n === 'anti-aging');
    if (allAntiAging) return true;
    // Not all house-brand → allow COD only if we know the delivery pincode is in-zone
    return pincodeInZone === true;
  }, [cartData, codRestrictionEnabled, pincodeInZone, prepaidOnly]);

  const [formData, setFormData] = useState({ name: '', phone: '', email: '', house_number: '', area: '', city: '', pincode: '', state: '' });
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState({});
  const [savedAddresses, setSavedAddresses] = useState([]);
  const [selectedAddressId, setSelectedAddressId] = useState('');
  // Instant Delivery — draggable-pin state. Seed from LocationStrip if user
  // already picked one; otherwise CheckoutMap falls back to Kozhikode.
  const [pin, setPin] = useState(() => {
    try {
      const raw = localStorage.getItem(STORED_LOCATION_KEY);
      const j = raw ? JSON.parse(raw) : null;
      return (j && j.lat && j.lng) ? { lat: j.lat, lng: j.lng } : null;
    } catch (_) { return null; }
  });
  const [pinInfo, setPinInfo] = useState(null); // { lat, lng, coverage, address }
  // Auto-flip to prepaid when COD becomes unavailable while user had it selected.
  // Uses a proper useEffect (never setState during render) so React can't blow up
  // the cart/checkout tree. Declared AFTER pinInfo state to avoid TDZ.
  useEffect(() => {
    if (paymentMethod === 'COD' && (prepaidOnly || (!codAvailable && !(pinInfo?.coverage?.instant_available)))) {
      setPaymentMethod('prepaid');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [codAvailable, paymentMethod, pinInfo, prepaidOnly]);

  // Auto-disable prepaid bonus when user selects COD — server would strip it
  // anyway, but keeping the UI in sync avoids a confusing "₹100 saved" chip
  // that vanishes after the next re-validate.
  useEffect(() => {
    if (paymentMethod !== 'prepaid' && prepaidBonus) {
      setPrepaidBonus(false);
    }
  }, [paymentMethod, prepaidBonus]);

  // Auto-disable prepaid bonus when subtotal drops below the ₹800 threshold
  // (e.g., user removes an item after opting in). Server strips it anyway,
  // but this keeps the UI honest so the user doesn't see a phantom discount.
  useEffect(() => {
    if (!prepaidBonus || !cartData) return;
    const min = cartData.prepaid_bonus_min_subtotal ?? 800;
    if ((cartData.subtotal || 0) < min) {
      setPrepaidBonus(false);
    }
  }, [cartData, prepaidBonus]);

  // Load saved addresses if customer is logged in
  useEffect(() => {
    const token = (typeof window !== 'undefined') ? localStorage.getItem('cg_auth_token') : null;
    if (!token) return;
    axios.get(`${API}/api/customer/addresses`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => {
        const list = r.data?.addresses || [];
        setSavedAddresses(list);
        // Auto-fill from default address if formData is empty
        const def = list.find(a => a.is_default) || list[0];
        if (def && !formData.name) {
          setSelectedAddressId(def.id);
          setFormData({
            name: def.name || '', phone: def.phone || '', email: formData.email || '',
            house_number: def.house_number || '', area: def.area || '',
            city: def.city || '', pincode: def.pincode || '', state: def.state || '',
          });
        }
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const applyAddress = (id) => {
    const a = savedAddresses.find(x => x.id === id);
    if (!a) return;
    setSelectedAddressId(id);
    setFormData({
      name: a.name || '', phone: a.phone || '', email: formData.email || '',
      house_number: a.house_number || '', area: a.area || '',
      city: a.city || '', pincode: a.pincode || '', state: a.state || '',
    });
  };

  useEffect(() => {
    trackAction('view_checkout', { step: 'checkout_started' });
    // Meta Pixel — Checkout PageView (in addition to InitiateCheckout fired from cart)
    if (typeof window !== 'undefined' && window.fbq) {
      window.fbq('track', 'PageView', { page_name: 'checkout', content_category: 'Checkout' });
    }
    // Pre-fill form from the logged-in user (if any)
    try {
      const u = JSON.parse(localStorage.getItem('cg_auth_user') || 'null');
      if (u) {
        setFormData(prev => ({
          ...prev,
          email: prev.email || u.email || '',
          phone: prev.phone || u.phone || '',
          name:  prev.name  || u.name  || '',
        }));
      }
    } catch { /* ignore */ }
    if (!cartData) {
      const cart = getCart();
      if (!cart.items.length) { navigate('/cart'); return; }
      axios.post(`${API}/api/cart/validate`, { items: cart.items, payment_method: paymentMethod, coupon_code: coupon?.code, gift_card_code: giftCard?.code || null, prepaid_bonus: prepaidBonus, promo_active: promoActive, session_id: getSessionId() })
        .then(res => setCartData(res.data))
        .catch((err) => {
          // Feb-2026: "other brands out of stock" master-switch gate. The
          // server returns 409 with a machine-readable reason so we can
          // show a friendly modal and bounce the customer back home.
          const d = err?.response?.data?.detail;
          if (err?.response?.status === 409 && d?.reason === 'other_brands_out_of_stock') {
            setOtherBrandsBlock(d);
          } else {
            navigate('/cart');
          }
        });
    }
  }, []);

  // Other-brands out-of-stock block (server-driven — see 409 above)
  const [otherBrandsBlock, setOtherBrandsBlock] = useState(null);

  // Pincode-based instant-delivery zone check (Feb-2026). Runs whenever
  // the user has typed a 6-digit pincode; sets `pincodeInZone` which the
  // COD payment gate above OR's with the map-based coverage. Fixes the
  // reported bug: prepaid-only mode wasn't kicking in on non-Celesta-Glow
  // brand items because the customer never gave browser geolocation.
  // (pincodeInZone useState is declared above the codAvailable useMemo to
  // avoid a TDZ crash — do not move.)

  const handlePincodeChange = async (pincode) => {
    setFormData(prev => ({ ...prev, pincode }));
    if (pincode.length === 6 && /^\d{6}$/.test(pincode)) {
      // Fire both look-ups in parallel — state/city + warehouse zone.
      try {
        const [stateRes, zoneRes] = await Promise.allSettled([
          axios.get(`${API}/api/pincode/${pincode}`),
          axios.get(`${API}/api/delivery/coverage-by-pincode`, { params: { pincode } }),
        ]);
        if (stateRes.status === 'fulfilled') {
          setFormData(prev => ({
            ...prev,
            state: stateRes.value.data.state || prev.state,
            city: stateRes.value.data.city || stateRes.value.data.district || prev.city,
          }));
        }
        if (zoneRes.status === 'fulfilled') {
          setPincodeInZone(!!zoneRes.value.data?.in_zone);
        }
      } catch {}
    } else {
      setPincodeInZone(null);
    }
  };

  // Stable change handler — passed to memoized Field, prevents input remounts on keystroke.
  const handleFieldChange = React.useCallback((field, value) => {
    if (field === 'pincode') {
      handlePincodeChange(value);
    } else {
      setFormData(prev => ({ ...prev, [field]: value }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-validate cart when payment method, prepaid-bonus flag, OR promo timer
  // state changes so the summary reflects the current perks live. Debounced
  // 250ms to coalesce React state batches.
  useEffect(() => {
    if (!cartData) return;
    const cart = getCart();
    if (!cart.items.length) return;
    const t = setTimeout(() => {
      axios.post(`${API}/api/cart/validate`, { items: cart.items, payment_method: paymentMethod, coupon_code: coupon?.code, gift_card_code: giftCard?.code || null, prepaid_bonus: prepaidBonus, promo_active: promoActive, session_id: getSessionId() })
        .then(res => setCartData(res.data))
        .catch((err) => {
          const d = err?.response?.data?.detail;
          if (err?.response?.status === 409 && d?.reason === 'other_brands_out_of_stock') {
            setOtherBrandsBlock(d);
          }
        });
    }, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paymentMethod, prepaidBonus, promoActive]);

  // Auto-untoggle prepaid bonus the moment the 3-min timer expires so the UI
  // doesn't lie. Server strips it anyway (promo_active=false), but this keeps
  // the "Applied" chip in sync.
  useEffect(() => {
    if (!promoActive && prepaidBonus) {
      setPrepaidBonus(false);
    }
  }, [promoActive, prepaidBonus]);

  // PERF: persist the freshest cartData to sessionStorage so a page refresh
  // or navigate-back to /checkout paints the summary in one frame instead of
  // waiting on the network. Storage is scoped per tab (session) and expires
  // after 5 minutes (checked on hydrate above).
  useEffect(() => {
    if (!cartData) return;
    try {
      sessionStorage.setItem('cg_checkout_cart_v1', JSON.stringify({ ...cartData, __at: Date.now() }));
    } catch (_) {}
  }, [cartData]);

  const validate = () => {
    const e = {};
    if (!formData.name.trim()) e.name = 'Required';
    if (!formData.phone.match(/^[6-9]\d{9}$/)) e.phone = 'Valid 10-digit phone';
    // Strict email format: no consecutive dots, must have proper local/domain/TLD
    const emailRe = /^[A-Za-z0-9]+([._-][A-Za-z0-9]+)*@[A-Za-z0-9]+([.-][A-Za-z0-9]+)*\.[A-Za-z]{2,}$/;
    if (!formData.email.trim()) e.email = 'Email is required';
    else if (!emailRe.test(formData.email.trim())) e.email = 'Enter a valid email (e.g., name@domain.com)';
    if (!formData.house_number.trim()) e.house_number = 'Required';
    if (!formData.area.trim()) e.area = 'Address required';
    if (!formData.pincode.match(/^\d{6}$/)) e.pincode = 'Valid pincode';
    if (!formData.state.trim()) e.state = 'Required';
    setErrors(e); return Object.keys(e).length === 0;
  };

  const placeOrder = async () => {
    if (!validate() || !cartData) return;
    setSubmitting(true);
    trackAction('payment_method_selected', { method: paymentMethod });
    const referralCode = (typeof window !== 'undefined') ? sessionStorage.getItem('referralCode') : null;
    // Attach the sale-campaign slug from sessionStorage so admin can attribute
    // orders back to specific /sale/... landing pages. Set on SalePage load.
    let campaign_slug = null;
    try { campaign_slug = sessionStorage.getItem('sale_campaign_slug') || null; } catch (_) { /* noop */ }
    const payload = { ...formData, payment_method: paymentMethod, amount: cartData.total, items: cartData.items, coupon_code: coupon?.code || null, coupon_discount: coupon?.discount || 0, referral_code: referralCode || null, gift_card_code: cartData.gift_card?.code || null, gift_card_discount: cartData.gift_card_discount || 0, campaign_slug,
      // Instant Delivery — pin coords + auto-assigned warehouse.
      delivery_lat: pinInfo?.lat || null,
      delivery_lng: pinInfo?.lng || null,
      delivery_type: pinInfo?.coverage?.delivery_type || null,
      assigned_warehouse_id: pinInfo?.coverage?.assigned_warehouse_id || null,
      // Prepaid ₹100 bonus flag (server enforces payment_method='prepaid').
      prepaid_bonus: prepaidBonus,
      // Flash offer window still open when the user hit Place Order
      promo_active: promoActive,
      // Session id (feeds the deterministic free-gift picker)
      session_id: getSessionId(),
      // Meta CAPI plumbing — cookies + UA. Server dedups the browser Pixel
      // Purchase event with the server-side one by event_id = order_id.
      fbp: getCookie('_fbp') || null,
      fbc: getCookie('_fbc') || null,
      client_user_agent: (typeof navigator !== 'undefined') ? navigator.userAgent : null,
    };
    const fireConversion = (orderId) => {
      trackAction('order_complete', { order_id: orderId, total: cartData.total, items: cartData.item_count, payment_method: paymentMethod });
      // Meta Pixel Purchase is fired exclusively on OrderSuccessPage — firing
      // here races with navigate() and browsers cancel the in-flight XHR on
      // SPA route change, causing Purchase events to silently drop (very common
      // failure mode for COD flows). GA is safe because gtag uses beacons.
      trackGAEvent('purchase', { transaction_id: orderId, value: cartData.total, currency: 'INR', items: cartData.item_count });
    };
    // Cache order + navigate with state so Order Success shows INSTANTLY (no loading spinner)
    const goToSuccess = (orderData) => {
      try { sessionStorage.setItem(`cg_order_${orderData.order_id}`, JSON.stringify(orderData)); } catch {}
      // One-time-use guard: clear the popup-claimed coupon code so it does NOT
      // auto-apply on the next order. We keep `discountClaimed=true` so the
      // popup never shows again to the same browser.
      try {
        localStorage.removeItem('discountCode');
        localStorage.removeItem('claimedDiscountCode');
      } catch { /* ignore */ }
      saveCart({ items: [] });
      navigate(`/order-success/${orderData.order_id}`, { state: { order: orderData } });
    };
    try {
      if (paymentMethod === 'prepaid') {
        const rzpOrder = await axios.post(`${API}/api/create-razorpay-order`, { amount: cartData.total });
        const options = {
          key: process.env.REACT_APP_RAZORPAY_KEY_ID || 'rzp_test_key', amount: rzpOrder.data.amount, currency: 'INR',
          name: 'Celesta Glow', description: `Order - ${cartData.item_count} items`, order_id: rzpOrder.data.id,
          handler: async (response) => {
            try {
              // Fire verify + create-order in PARALLEL — verify is just a signature check
              const [, orderResp] = await Promise.all([
                axios.post(`${API}/api/verify-payment`, response),
                axios.post(`${API}/api/orders`, payload),
              ]);
              fireConversion(orderResp.data.order_id);
              goToSuccess(orderResp.data);
            } catch (e) {
              alert(e?.response?.data?.detail || 'Payment verification failed');
              setSubmitting(false);
            }
          },
          prefill: { name: formData.name, contact: formData.phone, email: formData.email },
          theme: { color: '#16a34a' },
          // Reset button state when user closes the Razorpay modal without paying
          modal: {
            ondismiss: () => {
              trackAction('payment_modal_dismissed', { method: 'razorpay' });
              setSubmitting(false);
            },
            escape: true,
            backdropclose: false,
          },
        };
        // Razorpay SDK is no longer pre-loaded globally (removed from
        // index.html in the Jun 22 2026 perf pass). Inject it on demand
        // here so the homepage stays light. Subsequent checkouts find the
        // script already cached and resolve immediately.
        if (!window.Razorpay) {
          await new Promise((resolve, reject) => {
            const existing = document.getElementById('rzp-sdk');
            if (existing) { existing.addEventListener('load', resolve); existing.addEventListener('error', reject); return; }
            const s = document.createElement('script');
            s.id = 'rzp-sdk';
            s.src = 'https://checkout.razorpay.com/v1/checkout.js';
            s.async = true;
            s.onload = resolve;
            s.onerror = () => reject(new Error('Failed to load Razorpay'));
            document.head.appendChild(s);
          });
        }
        const rzp = new window.Razorpay(options);
        // Failed payment — also reset the button
        rzp.on('payment.failed', (resp) => {
          const reason = resp?.error?.description || 'Payment failed. Please try again.';
          alert(reason);
          setSubmitting(false);
        });
        rzp.open();
      } else {
        const order = await axios.post(`${API}/api/orders`, payload);
        fireConversion(order.data.order_id);
        goToSuccess(order.data);
      }
    } catch (err) {
      const detail = err?.response?.data?.detail || err?.message || 'Order failed. Please try again.';
      alert(detail);
      setSubmitting(false);
    }
  };

  if (otherBrandsBlock) {
    return (
      <div className="min-h-screen bg-stone-50 flex items-center justify-center p-4" data-testid="checkout-other-brands-block">
        <div className="max-w-md w-full bg-white rounded-3xl ring-1 ring-stone-200 shadow-xl p-6 sm:p-8 text-center">
          <div className="w-16 h-16 rounded-full bg-amber-100 flex items-center justify-center mx-auto mb-4">
            <Package size={28} className="text-amber-600" />
          </div>
          <h1 className="text-xl sm:text-2xl font-black text-stone-900 mb-2">Out of stock</h1>
          <p className="text-sm text-stone-600 leading-relaxed mb-5">
            {otherBrandsBlock.message}
          </p>
          {Array.isArray(otherBrandsBlock.offending_items) && otherBrandsBlock.offending_items.length > 0 && (
            <ul className="text-left text-xs text-stone-500 mb-5 bg-stone-50 rounded-xl p-3 space-y-1">
              {otherBrandsBlock.offending_items.slice(0, 4).map((it, i) => (
                <li key={i}>• {it.name} <span className="text-stone-400">({it.brand})</span></li>
              ))}
            </ul>
          )}
          <button
            onClick={() => navigate(otherBrandsBlock.redirect_to || '/')}
            className="w-full py-3.5 rounded-2xl bg-green-600 hover:bg-green-700 text-white font-black text-sm tracking-wider uppercase shadow-lg"
            data-testid="checkout-other-brands-cta"
          >
            Explore new anti-aging launches
          </button>
        </div>
      </div>
    );
  }

  if (!cartData) return null;

  return (
    <div className="min-h-screen bg-stone-50" data-testid="checkout-page">
      {/* Premium Trust Strip */}
      <div className="bg-green-800 text-white py-2.5 px-4">
        <div className="max-w-4xl mx-auto flex items-center justify-center gap-5 sm:gap-8 text-xs sm:text-xs font-medium">
          <span className="flex items-center gap-1.5"><Lock size={13} /> Secure Checkout</span>
          <span className="flex items-center gap-1.5"><Truck size={13} /> Free Shipping</span>
          <span className="flex items-center gap-1.5"><Star size={13} /> 4.8 Rating</span>
          <span className="flex items-center gap-1.5 hidden sm:flex"><Shield size={13} /> 7-Day Sealed Return</span>
        </div>
      </div>

      {/* Surprise reveal — one-shot per checkout session. When eligible we now
          reveal a FREE product (sunscreen / under-eye / cleanser) instead of
          the old ₹50 flash discount. Server locks the pick via session_id. */}
      {promoActive && cartData?.free_gift && (
        <CheckoutSurpriseModal
          amount={0}
          gift={cartData.free_gift}
          minSubtotal={cartData?.free_gift_min_subtotal || 1000}
          timerLabel="10-minute flash offer"
          onClaim={() => {
            if (paymentMethod !== 'prepaid') setPaymentMethod('prepaid');
          }}
        />
      )}

      <div className="max-w-4xl mx-auto px-4 py-4 sm:py-6">
        <div className="flex items-center gap-3 mb-5">
          <Link to="/cart" className="p-2 hover:bg-white rounded-xl transition-colors"><ArrowLeft size={20} /></Link>
          <div>
            <h1 className="text-lg font-bold text-gray-900">Checkout</h1>
            <p className="text-xs text-gray-400">{cartData.item_count} items | Secure checkout</p>
          </div>
        </div>

        {/* ---------- Flash Offer Banner (3-min urgency + 2-day cooldown) ---------- */}
        {promoActive ? (
          <div
            data-testid="promo-timer-banner"
            className="relative overflow-hidden rounded-2xl mb-5 border border-amber-300/60 shadow-[0_10px_30px_-12px_rgba(217,119,6,0.5)]"
          >
            {/* Warm gradient background */}
            <div
              aria-hidden
              className="absolute inset-0"
              style={{ background: 'linear-gradient(120deg,#f59e0b 0%,#f97316 45%,#ef4444 100%)' }}
            />
            {/* Subtle animated shine */}
            <div
              aria-hidden
              className="absolute inset-y-0 -left-16 w-16 opacity-40 blur-xl"
              style={{ background: 'linear-gradient(90deg,transparent,white,transparent)', animation: 'cgShine 3.6s ease-in-out infinite' }}
            />
            <style>{`@keyframes cgShine{0%{transform:translateX(0)}100%{transform:translateX(600%)}}`}</style>

            <div className="relative flex items-center gap-3 px-4 py-3">
              {/* Pulsing dot */}
              <span className="relative flex-shrink-0 flex h-3 w-3">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-70"></span>
                <span className="relative inline-flex rounded-full h-3 w-3 bg-white"></span>
              </span>

              <div className="flex-1 min-w-0 leading-tight">
                <p className="font-black text-white text-[14px] tracking-tight">
                  Your special price expires soon
                </p>
                <p className="text-white/90 text-[11.5px] mt-0.5 font-medium">
                  ₹100 OFF · Zero Tax · Free Delivery — only while the timer runs.
                </p>
              </div>

              {/* Countdown clock */}
              <div
                className="flex-shrink-0 bg-white/95 text-red-600 rounded-xl px-3 py-1.5 font-black text-[15px] tabular-nums tracking-widest shadow-inner"
                data-testid="promo-timer-clock"
              >
                {String(promoMinutes).padStart(2, '0')}:{String(promoSeconds).padStart(2, '0')}
              </div>
            </div>
          </div>
        ) : (
          <div
            data-testid="promo-timer-expired"
            className="rounded-2xl mb-5 border border-stone-200 bg-white shadow-sm"
          >
            <div className="flex items-center gap-3 px-4 py-3">
              <div className="flex-shrink-0 w-9 h-9 rounded-xl bg-stone-100 flex items-center justify-center">
                <Clock size={18} className="text-stone-500" />
              </div>
              <div className="flex-1 min-w-0 leading-tight">
                <p className="font-bold text-stone-800 text-[13.5px] tracking-tight">
                  Offer window closed — full price shown below
                </p>
                <p className="text-stone-500 text-[11.5px] mt-0.5">
                  {hoursUntilReactivate > 24
                    ? `Come back in ~${Math.ceil(hoursUntilReactivate/24)} day${Math.ceil(hoursUntilReactivate/24)===1?'':'s'} to unlock the promo again.`
                    : `Come back in ~${hoursUntilReactivate} hour${hoursUntilReactivate===1?'':'s'} to unlock the promo again.`}
                </p>
              </div>
            </div>
          </div>
        )}
        {/* ---------- end banner ---------- */}

        <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
          {/* Form */}
          <div className="lg:col-span-3 space-y-4">
            <div className="bg-white rounded-2xl p-5 border border-gray-100 shadow-sm">
              <h2 className="font-bold text-gray-900 text-sm mb-4 flex items-center gap-2"><MapPin size={16} className="text-green-600" /> Delivery Address</h2>

              {/* Instant Delivery — draggable pin. Sets delivery_lat/lng + coverage on the order. */}
              <div className="mb-4">
                <CheckoutMap initial={pin} onChange={(info) => {
                  setPinInfo(info);
                  setPin({ lat: info.lat, lng: info.lng });
                  // Auto-fill address fields from the reverse-geocode payload —
                  // only if the user hasn't already typed something into that field
                  // (so we never clobber their manual edits).
                  setFormData((prev) => ({
                    ...prev,
                    city: prev.city || info.city || info.locality || '',
                    state: prev.state || info.state || '',
                    pincode: prev.pincode || info.pincode || '',
                    area: prev.area || info.locality || '',
                  }));
                }} />
              </div>

              {/* Saved addresses selector (logged-in customers) */}
              {savedAddresses.length > 0 && (
                <div className="mb-4 -mt-2" data-testid="checkout-saved-addresses">
                  <label className="block text-[11px] font-bold text-gray-400 uppercase tracking-wider mb-1.5">Use a saved address</label>
                  <div className="flex flex-wrap gap-2">
                    {savedAddresses.map((a) => (
                      <button
                        key={a.id}
                        type="button"
                        onClick={() => applyAddress(a.id)}
                        className={`px-3 py-2 rounded-xl text-xs font-bold transition-all ${selectedAddressId === a.id ? 'bg-green-600 text-white ring-2 ring-green-300' : 'bg-stone-50 text-stone-700 ring-1 ring-stone-200 hover:bg-stone-100'}`}
                        data-testid={`checkout-saved-addr-${a.id}`}
                      >
                        {a.label || 'Address'} · {a.pincode}
                        {a.is_default && <span className="ml-1 opacity-70">★</span>}
                      </button>
                    ))}
                    <button
                      type="button"
                      onClick={() => { setSelectedAddressId(''); setFormData({ name: '', phone: '', email: formData.email, house_number: '', area: '', city: '', pincode: '', state: '' }); }}
                      className="px-3 py-2 rounded-xl text-xs font-bold bg-white ring-1 ring-stone-200 text-stone-500 hover:bg-stone-50"
                      data-testid="checkout-addr-new"
                    >
                      + New
                    </button>
                  </div>
                </div>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <Field label="Full Name" field="name" placeholder="Your full name" value={formData.name} error={errors.name} onChange={handleFieldChange} />
                <Field label="Phone" field="phone" type="tel" inputMode="tel" placeholder="10-digit number" value={formData.phone} error={errors.phone} onChange={handleFieldChange} />
                <Field label="Email" field="email" type="email" inputMode="email" placeholder="email@example.com" span value={formData.email} error={errors.email} onChange={handleFieldChange} />
                <Field label="House / Flat No." field="house_number" placeholder="House no, building, floor" span value={formData.house_number} error={errors.house_number} onChange={handleFieldChange} />
                <Field label="Address" field="area" placeholder="Street, area, landmark" span value={formData.area} error={errors.area} onChange={handleFieldChange} />
                <Field label="Pincode" field="pincode" inputMode="numeric" placeholder="6-digit pincode" value={formData.pincode} error={errors.pincode} onChange={handleFieldChange} />
                <Field label="City" field="city" placeholder="City / Locality" value={formData.city} error={errors.city} onChange={handleFieldChange} />
                <Field label="State" field="state" placeholder="State" span value={formData.state} error={errors.state} onChange={handleFieldChange} />
              </div>

              {/* Inline ETA after pincode — suppressed when Instant Delivery is available,
                  since CheckoutMap already surfaces the "45-55 min / 1-2 hr" ETA banner. */}
              {!pinInfo?.coverage?.instant_available && formData.pincode && /^\d{6}$/.test(formData.pincode) && formData.city && (
                <div className="mt-3 bg-green-50 border border-green-200 rounded-xl p-3 flex items-center gap-2.5" data-testid="checkout-eta-pill">
                  <Truck size={15} className="text-green-700 flex-shrink-0" />
                  <p className="text-xs text-green-900">
                    Delivers to <strong>{formData.city}{formData.state ? `, ${formData.state}` : ''}</strong> in{' '}
                    <strong className="text-green-700">{paymentMethod === 'prepaid' ? '1–3 business days' : '4–6 business days'}</strong>
                  </p>
                </div>
              )}
            </div>

              {/* Payment Method */}
              <div className="bg-white rounded-2xl p-5 border border-gray-100 shadow-sm">
                <h2 className="font-bold text-gray-900 text-sm mb-3">Payment Method</h2>

                {/* ₹100 OFF Prepaid Bonus — clean single-column card */}
                {(() => {
                  const meetsMin = (cartData?.subtotal || 0) >= (cartData?.prepaid_bonus_min_subtotal ?? 800);
                  const eligible = meetsMin && promoActive;
                  const shortBy = Math.max(0, (cartData?.prepaid_bonus_min_subtotal ?? 800) - (cartData?.subtotal || 0));
                  const lockReason = !promoActive
                    ? 'Promo timer ended · come back later'
                    : !meetsMin
                      ? `Add ₹${shortBy.toLocaleString()} more to unlock`
                      : null;
                  const ctaLabel = !promoActive ? 'Expired' : !meetsMin ? 'Locked' : (prepaidBonus ? '✓ Applied' : 'Grab Now');
                  return (
                <button
                  type="button"
                  disabled={!eligible}
                  onClick={() => {
                    if (!eligible) return;
                    const next = !prepaidBonus;
                    if (next) setPaymentMethod('prepaid');
                    setPrepaidBonus(next);
                    try { trackAction(next ? 'prepaid_bonus_claim' : 'prepaid_bonus_unclaim', { amount: 100 }); } catch {}
                  }}
                  data-testid="prepaid-bonus-toggle"
                  className={`relative w-full mb-3 overflow-hidden rounded-2xl border text-left transition-all duration-300 ${
                    !eligible
                      ? 'border-gray-200 bg-gray-50 cursor-not-allowed opacity-80'
                      : prepaidBonus
                        ? 'border-emerald-500 bg-gradient-to-br from-emerald-500 via-emerald-500 to-emerald-600 shadow-[0_10px_28px_-10px_rgba(16,185,129,0.6)]'
                        : 'border-emerald-200 bg-gradient-to-br from-emerald-50 via-white to-emerald-50 hover:border-emerald-400 hover:shadow-md'
                  }`}
                >
                  <div className="relative flex items-center gap-3 px-4 py-3.5">
                    {/* Icon */}
                    <div className={`flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center ${
                      !eligible ? 'bg-gray-200 text-gray-500'
                        : prepaidBonus ? 'bg-white/20 text-white ring-1 ring-white/40'
                        : 'bg-emerald-600 text-white'
                    }`}>
                      <Gift size={20} strokeWidth={2.5} />
                    </div>

                    {/* Text block */}
                    <div className="flex-1 min-w-0 leading-tight">
                      <p className={`font-extrabold text-[15px] tracking-tight ${
                        !eligible ? 'text-gray-700' : prepaidBonus ? 'text-white' : 'text-emerald-900'
                      }`}>
                        Flat ₹100 OFF
                      </p>
                      <p className={`text-[11.5px] mt-0.5 font-medium ${
                        !eligible ? 'text-gray-500'
                          : prepaidBonus ? 'text-emerald-50/95'
                          : 'text-emerald-700'
                      }`}>
                        {lockReason
                          ? lockReason
                          : prepaidBonus
                            ? 'Applied · Prepaid · Min ₹800'
                            : 'Prepaid orders · Min cart ₹800'}
                      </p>
                    </div>

                    {/* Compact CTA */}
                    <span className={`flex-shrink-0 rounded-full px-3.5 py-1.5 text-[10.5px] font-black uppercase tracking-wider whitespace-nowrap ${
                      !eligible ? 'bg-gray-200 text-gray-500'
                        : prepaidBonus ? 'bg-white text-emerald-700'
                        : 'bg-emerald-700 text-white'
                    }`}>
                      {ctaLabel}
                    </span>
                  </div>
                </button>
                  );
                })()}

                {(() => {
                  const instantOk = !!pinInfo?.coverage?.instant_available;
                  const canCOD = (codAvailable || instantOk) && !prepaidOnly;
                  return (
                    <div className="space-y-2.5">
                      <label className={`flex items-center gap-3 p-3.5 rounded-xl border-2 cursor-pointer transition-all ${paymentMethod === 'prepaid' ? 'border-green-500 bg-green-50/50 shadow-sm' : 'border-gray-100 hover:border-gray-200'}`}>
                        <input type="radio" name="pay" checked={paymentMethod === 'prepaid'} onChange={() => setPaymentMethod('prepaid')} className="text-green-600 w-4 h-4" data-testid="pay-method-prepaid" />
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <p className="font-bold text-sm text-gray-900">Prepaid (UPI / Card)</p>
                            <span className="text-xs bg-green-600 text-white px-2 py-0.5 rounded-full font-bold">RECOMMENDED</span>
                          </div>
                          <p className="text-xs text-green-600 font-medium mt-0.5">Faster delivery · Best price</p>
                        </div>
                      </label>
                      {canCOD ? (
                        <label className={`flex items-center gap-3 p-3.5 rounded-xl border-2 cursor-pointer transition-all ${paymentMethod === 'COD' ? 'border-green-500 bg-green-50/50' : 'border-gray-100 hover:border-gray-200'}`}>
                          <input type="radio" name="pay" checked={paymentMethod === 'COD'} onChange={() => setPaymentMethod('COD')} className="text-green-600 w-4 h-4" data-testid="pay-method-cod" />
                          <div className="flex-1">
                            <div className="flex items-center gap-2">
                              <p className="font-bold text-sm text-gray-900">Cash on Delivery</p>
                              {instantOk && !codAvailable && (
                                <span className="text-[10px] bg-amber-500 text-white px-1.5 py-0.5 rounded-full font-bold uppercase tracking-wider">Instant Zone</span>
                              )}
                            </div>
                            <p className="text-xs text-gray-500 mt-0.5">₹0 advance · Pay full on delivery</p>
                          </div>
                        </label>
                      ) : (
                        <div className="flex items-start gap-2.5 p-3 rounded-xl bg-amber-50/70 border border-amber-200/60" data-testid="cod-unavailable-note">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-amber-600 mt-0.5 flex-shrink-0"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                          <div>
                            <p className="text-xs font-bold text-amber-800">Cash on Delivery not available</p>
                            <p className="text-[11px] text-amber-700 mt-0.5 leading-snug">COD is only offered on Celesta Glow&apos;s own anti-aging products, or when your address is in an <strong>instant-delivery zone</strong>. Prepaid works everywhere.</p>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })()}
              </div>

            {/* Volume / buy-more discount panel removed per business policy. */}

            {/* Referral Program */}
            <div className="bg-gradient-to-r from-purple-50 to-violet-50 rounded-2xl p-4 border border-purple-100">
              <div className="flex items-center gap-2 mb-2"><Gift size={16} className="text-purple-600" /><p className="text-xs font-bold text-purple-800">Earn Rewards After Purchase!</p></div>
              <p className="text-xs text-gray-600 leading-relaxed">Refer friends after checkout and earn ₹50 for every successful referral. <span className="font-semibold text-purple-700">2,847 customers referred friends this month!</span></p>
              <div className="grid grid-cols-2 gap-2 mt-3">
                <div className="bg-white rounded-xl p-2.5 text-center border border-purple-100">
                  <p className="text-base font-black text-purple-700">2,847</p>
                  <p className="text-xs text-purple-500 font-medium">Referrals This Month</p>
                </div>
                <div className="bg-white rounded-xl p-2.5 text-center border border-purple-100">
                  <p className="text-base font-black text-purple-700">₹1.42L</p>
                  <p className="text-xs text-purple-500 font-medium">Rewards Earned</p>
                </div>
              </div>
            </div>
          </div>

          {/* Order Summary */}
          <div className="lg:col-span-2">
            <div className="bg-white rounded-2xl p-4 border border-gray-100 shadow-sm sticky top-4">
              <p className="text-xs font-bold text-gray-400 uppercase tracking-[0.15em] mb-3">Order Summary</p>
              <div className="space-y-2 mb-3 max-h-36 overflow-y-auto">
                {cartData.items?.map((item, i) => (
                  <div key={i} className="flex justify-between items-center text-sm">
                    <span className="text-gray-600 truncate mr-2 flex-1">{item.short_name || item.name}</span>
                    <span className="text-xs text-gray-400 mr-2">x{item.quantity}</span>
                    <span className="font-medium text-gray-900">₹{item.line_total}</span>
                  </div>
                ))}
              </div>
              <div className="border-t border-gray-100 pt-3 space-y-1.5 text-sm">
                <div className="flex justify-between text-gray-400"><span>Subtotal</span><span>₹{cartData.subtotal?.toLocaleString()}</span></div>
                {cartData.discount > 0 && <div className="flex justify-between text-green-600"><span>Coupon Discount</span><span className="font-semibold">-₹{cartData.discount}</span></div>}
                {(cartData.tax_charges > 0 || cartData.sale_perks?.tax) && (
                  <div className="flex justify-between text-gray-400">
                    <span className="flex items-center gap-1.5">
                      Taxes &amp; Charges
                      {cartData.sale_perks?.tax && (
                        <span className="bg-amber-100 text-amber-800 text-[9px] font-bold px-1.5 py-0.5 rounded-full uppercase tracking-wider">
                          {cartData.sale_perks.reason || 'FLAT 50% OFF'}
                        </span>
                      )}
                    </span>
                    <span>
                      {cartData.sale_perks?.tax ? (
                        <>
                          {cartData.tax_charges_original > 0 && <span className="text-gray-300 line-through mr-1.5">₹{cartData.tax_charges_original}</span>}
                          <span className="text-green-600 font-bold">FREE</span>
                        </>
                      ) : (
                        <>
                          {cartData.tax_charges_original > cartData.tax_charges && <span className="text-gray-300 line-through mr-1.5">₹{cartData.tax_charges_original}</span>}
                          ₹{cartData.tax_charges}
                        </>
                      )}
                    </span>
                  </div>
                )}
                <div className="flex justify-between text-gray-400">
                  <span className="flex items-center gap-1.5">
                    Delivery
                    {cartData.sale_perks?.delivery && (
                      <span className="bg-amber-100 text-amber-800 text-[9px] font-bold px-1.5 py-0.5 rounded-full uppercase tracking-wider">
                        {cartData.sale_perks.reason || 'FLAT 50% OFF'}
                      </span>
                    )}
                  </span>
                  {cartData.sale_perks?.delivery ? (
                    <span>
                      {cartData.delivery_fee_original > 0 && <span className="text-gray-300 line-through mr-1.5">₹{cartData.delivery_fee_original}</span>}
                      <span className="text-green-600 font-bold">FREE</span>
                    </span>
                  ) : cartData.delivery_fee > 0
                    ? <span className="font-medium text-orange-600">₹{cartData.delivery_fee}</span>
                    : <span className="text-green-600 font-medium">FREE</span>
                  }
                </div>
                {cartData.packaging_fee > 0 && (
                  <div className="flex justify-between text-gray-500 text-xs">
                    <span>🌿 Eco-Friendly Packaging</span>
                    <span>₹{cartData.packaging_fee}</span>
                  </div>
                )}
                {cartData.gift_card_discount > 0 && (
                  <div className="flex justify-between text-rose-600 font-medium" data-testid="checkout-giftcard-row">
                    <span>🎁 Gift Card ({cartData.gift_card?.code})</span>
                    <span>-₹{cartData.gift_card_discount}</span>
                  </div>
                )}
                {cartData.prepaid_bonus_applied > 0 && (
                  <div className="flex justify-between text-emerald-700 font-semibold" data-testid="checkout-prepaid-bonus-row">
                    <span className="flex items-center gap-1.5">
                      <Gift size={13} strokeWidth={2.6} /> Prepaid Bonus
                    </span>
                    <span>-₹{cartData.prepaid_bonus_applied}</span>
                  </div>
                )}
                {cartData.free_gift && (
                  <div className="flex justify-between text-emerald-700 font-semibold" data-testid="checkout-free-gift-row">
                    <span className="flex items-center gap-1.5">
                      <Gift size={13} strokeWidth={2.6} /> FREE {cartData.free_gift.name}
                    </span>
                    <span>-₹{cartData.free_gift.mrp || 0}</span>
                  </div>
                )}
                {cartData.combo_bonus_applied > 0 && (
                  <div className="flex justify-between text-purple-700 font-semibold" data-testid="checkout-combo-bonus-row">
                    <span className="flex items-center gap-1.5">
                      <Award size={13} strokeWidth={2.6} /> Combo Bonus ₹{cartData.combo_bonus_applied} OFF
                    </span>
                    <span>-₹{cartData.combo_bonus_applied}</span>
                  </div>
                )}
                <div className="border-t border-gray-100 pt-2 flex justify-between font-bold text-gray-900 text-lg"><span>Total</span><span>₹{cartData.total?.toLocaleString()}</span></div>
              </div>

              {/* Free gift reveal — replaces the old ₹50 flash discount. Shows
                  the actual free product name + image once the user is on prepaid.
                  Server picks deterministically from session_id so this is stable. */}
              {promoActive && paymentMethod === 'prepaid' && cartData.free_gift && (
                <div className="mt-3 bg-gradient-to-r from-emerald-50 via-teal-50 to-emerald-50 border border-emerald-200 rounded-xl px-3.5 py-3 flex items-center gap-3" data-testid="checkout-free-gift-reveal">
                  {cartData.free_gift.image && (
                    <img src={cartData.free_gift.image} alt={cartData.free_gift.name} className="w-14 h-14 rounded-xl object-cover ring-1 ring-emerald-200 bg-white shrink-0" />
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-[10px] font-black tracking-[0.22em] text-emerald-700 uppercase mb-0.5">🎁 Your free gift</p>
                    <p className="text-sm font-black text-stone-900 leading-tight truncate">{cartData.free_gift.name}</p>
                    <p className="text-[11px] text-stone-600 leading-snug">
                      Worth <b>₹{cartData.free_gift.mrp}</b> — added FREE with your order
                    </p>
                  </div>
                </div>
              )}
              {promoActive && paymentMethod !== 'prepaid' && cartData.free_gift_eligible && (
                <div className="mt-3 bg-white border border-dashed border-emerald-300 rounded-xl px-3.5 py-2.5 flex items-center gap-2.5" data-testid="checkout-free-gift-cod-nudge">
                  <div className="w-8 h-8 rounded-full bg-emerald-100 text-emerald-700 flex items-center justify-center shrink-0">
                    <Gift size={16} />
                  </div>
                  <div className="text-[12px] leading-snug text-emerald-900">
                    Switch to <b>Prepaid</b> to unlock a <b>surprise free product</b> worth up to ₹999.
                  </div>
                </div>
              )}
              {promoActive && paymentMethod === 'prepaid' && !cartData.free_gift && (cartData.subtotal || 0) > 800 && (cartData.subtotal || 0) <= (cartData.free_gift_min_subtotal || 1000) && (
                <div className="mt-3 bg-white border border-dashed border-emerald-300 rounded-xl px-3.5 py-2.5 flex items-center gap-2.5" data-testid="checkout-free-gift-nudge">
                  <div className="w-8 h-8 rounded-full bg-emerald-100 text-emerald-700 flex items-center justify-center shrink-0">
                    <Gift size={16} />
                  </div>
                  <div className="text-[12px] leading-snug text-emerald-900">
                    Add <b>₹{Math.max(1, (cartData.free_gift_min_subtotal || 1000) + 1 - (cartData.subtotal || 0))}</b> more to unlock a <b>surprise free product</b>.
                  </div>
                </div>
              )}

              {cartData.gift_card?.code && cartData.gift_card_discount > 0 && (
                <div className="mt-3 bg-rose-50 border border-rose-200 rounded-xl p-2.5 text-center" data-testid="checkout-giftcard-note">
                  <p className="text-xs text-rose-800 font-bold">🎁 Gift card {cartData.gift_card.code} applied</p>
                  <p className="text-xs text-rose-700 mt-0.5">₹{cartData.gift_card.remaining_after} balance will remain after this order</p>
                </div>
              )}

              {cartData.savings > 0 && (
                <div className="mt-3 bg-gradient-to-r from-green-500 to-teal-500 rounded-xl p-3 text-center text-white">
                  <p className="text-xs font-bold">Total Savings: ₹{cartData.savings?.toLocaleString()}</p>
                  <p className="text-xs opacity-80">Incl. product discount + volume discount + free shipping</p>
                </div>
              )}

              <button onClick={placeOrder} disabled={submitting} className="w-full bg-green-600 hover:bg-green-700 disabled:bg-gray-300 text-white font-bold py-3.5 rounded-2xl mt-4 text-sm shadow-xl shadow-green-200/40 transition-all" data-testid="place-order-btn">
                {submitting ? 'Processing...' : paymentMethod === 'prepaid' ? `Pay ₹${cartData.total?.toLocaleString()}` : `Place COD Order`}
              </button>

              {/* Delivery Timeline — Instant Delivery orders get their ETA from CheckoutMap,
                  so we hide the standard shipping copy to avoid conflicting messaging. */}
              {pinInfo?.coverage?.instant_available ? (
                <div className="mt-3 text-center text-xs text-amber-700 font-semibold" data-testid="checkout-delivery-timeline-instant">
                  <p>Instant delivery · <strong>{pinInfo?.coverage?.nearest_warehouse?.distance_km <= 5 ? 'arrives in 45–55 minutes' : 'arrives in 1–2 hours'}</strong></p>
                </div>
              ) : (
                <div className="mt-3 text-center text-xs text-gray-500" data-testid="checkout-delivery-timeline-standard">
                  {paymentMethod === 'prepaid' ? (
                    <p>Faster delivery · <strong className="text-green-600">1–3 business days</strong></p>
                  ) : (
                    <p>Standard delivery · <strong>4–6 business days</strong></p>
                  )}
                </div>
              )}

              {/* Trust Icons */}
              <div className="mt-3 flex items-center justify-center gap-4 text-xs text-gray-400 font-medium">
                <span className="flex items-center gap-1"><Lock size={10} /> SSL Secure</span>
                <span className="flex items-center gap-1"><Shield size={10} /> Verified Brand</span>
                <span className="flex items-center gap-1"><Users size={10} /> 50K+ Served</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default CheckoutPage;
