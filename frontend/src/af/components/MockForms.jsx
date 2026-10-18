const F = ({ label, children, hint }) => (
  <div className="space-y-1">
    <label className="block text-[13px] font-semibold text-slate-800">{label}</label>
    {children}
    {hint && <p className="text-[11px] text-slate-500">{hint}</p>}
  </div>
);
import { useState } from "react";

const inp = "w-full border border-slate-300 rounded px-2.5 py-1.5 text-sm text-slate-900 bg-white focus:outline-none focus:border-slate-500";

export function AmazonForm() {
  const [step2, setStep2] = useState(false);
  return (
    <div className="bg-white text-slate-900 rounded-lg overflow-hidden" data-testid="mock-amazon-form">
      <div className="bg-[#232F3E] text-white px-5 py-3 text-sm font-semibold flex justify-between"><span>amazon <span className="text-amber-400">seller central</span></span><span className="text-xs opacity-70">Add a Product › Vital info</span></div>
      <div id="amazon-mock" className="p-5 grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="sm:col-span-2"><F label="Product Name" hint="Max 200 characters"><input name="item_name" maxLength={200} placeholder="e.g. Brand + Product + Key feature + Size" className={inp} /></F></div>
        <F label="Brand Name"><input name="brand_name" placeholder="Brand" className={inp} /></F>
        <F label="Manufacturer"><input name="manufacturer" placeholder="Manufacturer name" className={inp} /></F>
        <F label="Item Volume"><input name="item_volume" placeholder="e.g. 200 ml" className={inp} /></F>
        <F label="Your Price (INR)"><input name="standard_price" type="number" placeholder="0.00" className={inp} /></F>
        <F label="Maximum Retail Price"><input name="mrp" type="number" placeholder="MRP" className={inp} /></F>
        <F label="Hair Type"><select name="hair_type" className={inp}><option value="">-Select-</option><option>All Hair Types</option><option>Dry</option><option>Oily</option><option>Curly</option><option>Damaged</option></select></F>
        <div className="sm:col-span-2"><F label="Bullet Point 1"><input name="bullet_point1" maxLength={255} placeholder="Key product feature" className={inp} /></F></div>
        <div className="sm:col-span-2"><F label="Bullet Point 2"><input name="bullet_point2" maxLength={255} placeholder="Key product feature" className={inp} /></F></div>
        <div className="sm:col-span-2"><F label="Bullet Point 3"><input name="bullet_point3" maxLength={255} placeholder="Key product feature" className={inp} /></F></div>
        <div className="sm:col-span-2"><F label="Ingredients"><textarea name="ingredients" rows={2} placeholder="List the ingredients" className={inp} /></F></div>
        <div className="sm:col-span-2"><F label="Product Description"><textarea name="product_description" rows={3} placeholder="Describe your product" className={inp} /></F></div>
        <div className="sm:col-span-2"><F label="Search Terms"><input name="generic_keywords" placeholder="Keywords separated by commas" className={inp} /></F></div>
        {!step2 && <button type="button" data-testid="amazon-next-step-button" onClick={() => setStep2(true)} className="sm:col-span-2 justify-self-end px-4 py-2 rounded bg-[#FFD814] text-black text-sm font-semibold">Save and continue to Offer</button>}
        {step2 && (
          <div className="sm:col-span-2 grid grid-cols-1 sm:grid-cols-2 gap-4 pt-4 border-t border-slate-200" data-testid="amazon-offer-step">
            <p className="sm:col-span-2 text-sm font-bold">Step 2 · Offer</p>
            <F label="Seller SKU"><input name="item_sku" placeholder="Unique SKU" className={inp} /></F>
            <F label="Quantity"><input name="quantity" type="number" placeholder="Stock units" className={inp} /></F>
            <F label="Condition"><select name="condition_type" className={inp}><option value="">-Select-</option><option>New</option><option>Used - Like New</option></select></F>
            <F label="Fulfillment Channel"><select name="fulfillment" className={inp}><option value="">-Select-</option><option>Fulfilled by Merchant</option><option>Fulfilled by Amazon</option></select></F>
            <F label="Handling Time (days)"><input name="handling_time" type="number" placeholder="e.g. 2" className={inp} /></F>
            <F label="HSN Code"><input name="hsn_code" placeholder="HSN" className={inp} /></F>
          </div>
        )}
      </div>
    </div>
  );
}

export function FlipkartForm() {
  return (
    <div className="bg-white text-slate-900 rounded-lg overflow-hidden" data-testid="mock-flipkart-form">
      <div className="bg-[#2874F0] text-white px-5 py-3 text-sm font-semibold flex justify-between"><span>Flipkart <span className="italic text-yellow-300">Seller Hub</span></span><span className="text-xs opacity-80">Add Single Listing</span></div>
      <div id="flipkart-mock" className="p-5 grid grid-cols-1 sm:grid-cols-2 gap-4">
        <F label="Seller SKU ID"><input name="sku_id" placeholder="Enter SKU ID" className={inp} /></F>
        <F label="Listing Status"><select name="listing_status" className={inp}><option value="">Select</option><option>Active</option><option>Inactive</option></select></F>
        <F label="MRP"><input name="mrp" placeholder="Enter MRP" className={inp} /></F>
        <F label="Your selling price"><input name="selling_price" placeholder="Enter selling price" className={inp} /></F>
        <F label="Brand"><input name="brand" placeholder="Enter Brand" className={inp} /></F>
        <F label="Model Name"><input name="model_name" placeholder="Enter Model Name" className={inp} /></F>
        <F label="Quantity"><input name="quantity" placeholder="e.g. 200" className={inp} /></F>
        <F label="Quantity Unit"><select name="quantity_unit" className={inp}><option value="">Select</option><option>ml</option><option>l</option><option>g</option></select></F>
        <F label="Ideal For"><select name="ideal_for" className={inp}><option value="">Select</option><option>Men</option><option>Women</option><option>Men &amp; Women</option></select></F>
        <F label="Key Ingredients"><input name="key_ingredients" placeholder="Enter key ingredients" className={inp} /></F>
        <div className="sm:col-span-2"><F label="Description"><textarea name="description" rows={3} placeholder="Enter product description" className={inp} /></F></div>
        <div className="sm:col-span-2"><F label="Search Keywords"><input name="keywords" placeholder="Enter search keywords" className={inp} /></F></div>
      </div>
    </div>
  );
}
