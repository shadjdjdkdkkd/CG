import "@/af/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/af/components/ui/sonner";
import Layout from "@/af/components/Layout";
import Dashboard from "@/af/pages/Dashboard";
import Products from "@/af/pages/Products";
import Formats from "@/af/pages/Formats";
import Playground from "@/af/pages/Playground";
import Extension from "@/af/pages/Extension";
import History from "@/af/pages/History";
import Autopilot from "@/af/pages/Autopilot";
import Styles from "@/af/pages/Styles";
import Login from "@/af/pages/Login";
import Account from "@/af/pages/Account";
import { TOKEN_KEY } from "@/af/lib/api";

const Protected = () => (localStorage.getItem(TOKEN_KEY) ? <Layout /> : <Navigate to="/login" replace />);

function App() {
  return (
    <BrowserRouter basename="/admin/amazon-flipkart">
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<Protected />}>
          <Route path="/account" element={<Account />} />
          <Route path="/autopilot" element={<Autopilot />} />
          <Route path="/styles" element={<Styles />} />
          <Route path="/" element={<Dashboard />} />
          <Route path="/products" element={<Products />} />
          <Route path="/formats" element={<Formats />} />
          <Route path="/playground" element={<Playground />} />
          <Route path="/extension" element={<Extension />} />
          <Route path="/history" element={<History />} />
        </Route>
      </Routes>
      <Toaster theme="dark" position="bottom-right" />
    </BrowserRouter>
  );
}

export default App;
