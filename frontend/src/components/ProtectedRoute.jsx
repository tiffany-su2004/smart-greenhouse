import { Navigate } from "react-router-dom";

export default function ProtectedRoute({ children }) {
  const token = localStorage.getItem("access_token");

  console.log("ProtectedRoute token:", token);

  if (!token) {
    console.log("No token → redirecting");
    return <Navigate to="/login" replace />;
  }

  console.log("Token exists → rendering children");
  return children;
}