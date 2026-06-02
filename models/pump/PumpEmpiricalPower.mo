model PumpEmpiricalPower
  input Real m_flow_in(unit="kg/s", start=100.0)
    "Measured pump mass flow input";
  input Real y_in(unit="1", start=1.0)
    "Normalized pump speed or frequency input";

  parameter Real P_nominal(unit="W") = 40000.0 annotation(Evaluate=false);
  parameter Real m_flow_nominal(unit="kg/s") = 100.0 annotation(Evaluate=false);
  parameter Real y_min(unit="1") = 0.05 annotation(Evaluate=false);
  parameter Real y_max(unit="1") = 1.20 annotation(Evaluate=false);
  parameter Real c0(unit="1") = 0.0 annotation(Evaluate=false);
  parameter Real c1(unit="1") = 0.0 annotation(Evaluate=false);
  parameter Real c2(unit="1") = 0.0 annotation(Evaluate=false);
  parameter Real c3(unit="1") = 1.0 annotation(Evaluate=false);
  parameter Real c4(unit="1") = 0.0 annotation(Evaluate=false);

  output Real P_s(unit="W") "Simulated electrical power";
  output Real m_flow_s(unit="kg/s") "Echoed mass flow";
  output Real y_s(unit="1") "Clamped normalized speed";
  output Real phi(unit="1") "Normalized mass flow";

equation
  y_s = min(max(y_in, y_min), y_max);
  m_flow_s = max(0.0, m_flow_in);
  phi = max(0.0, m_flow_s / max(1e-6, m_flow_nominal));
  P_s = max(0.0, P_nominal * (c0 + c1 * phi + c2 * y_s + c3 * y_s ^ 3 + c4 * phi * y_s));

annotation(
  experiment(StartTime=0, StopTime=86400, Interval=300, Tolerance=1e-6),
  Documentation(info="<html><p>Empirical pump power model for Site A pump auto-modelling. It is intentionally minimal: measured flow and normalized speed are inputs, and electrical power is the scored output.</p></html>"));
end PumpEmpiricalPower;
