model SiteAPumpMblSpeedSystemCurve
  "Site A pump wrapper using Buildings SpeedControlled_y and a simple system resistance"
  package Medium = Buildings.Media.Water;

  Modelica.Blocks.Interfaces.RealInput y_in(unit="1")
    "Normalized speed command, frequency divided by 50 Hz";

  parameter Modelica.Units.SI.MassFlowRate m_flow_nominal = 100.0
    "Nominal mass flow rate" annotation(Evaluate=false);
  parameter Modelica.Units.SI.PressureDifference dp_nominal = 300000.0
    "Nominal pump pressure rise" annotation(Evaluate=false);
  parameter Modelica.Units.SI.PressureDifference dp_system_nominal = 250000.0
    "Nominal system pressure drop" annotation(Evaluate=false);
  parameter Modelica.Units.SI.Power P_nominal = 40000.0
    "Nominal electrical power" annotation(Evaluate=false);
  parameter Real P_scale(unit="1") = 1.0
    "Electrical power scale factor for calibration" annotation(Evaluate=false);
  parameter Real y_min(unit="1") = 0.05 annotation(Evaluate=false);
  parameter Real y_max(unit="1") = 1.20 annotation(Evaluate=false);
  parameter Real rho_nominal(unit="kg/m3") = 997.0 annotation(Evaluate=false);
  parameter Real g(unit="m/s2") = 9.80665 annotation(Evaluate=false);

  output Real P_s(unit="W") "Simulated electrical power";
  output Real m_flow_s(unit="kg/s") "Simulated mass flow";
  output Real dp_s(unit="Pa") "Inferred pump pressure rise";
  output Real head_s(unit="m") "Inferred pump head";
  output Real y_s(unit="1") "Clamped normalized speed";

  Buildings.Fluid.Sources.Boundary_pT source(
    redeclare package Medium = Medium,
    p=300000,
    T=293.15,
    nPorts=1) "Upstream pressure boundary";

  Buildings.Fluid.Sources.Boundary_pT sink(
    redeclare package Medium = Medium,
    p=300000,
    T=293.15,
    nPorts=1) "Downstream pressure boundary";

  Buildings.Fluid.Movers.Preconfigured.SpeedControlled_y pump(
    redeclare package Medium = Medium,
    use_riseTime=false,
    energyDynamics=Modelica.Fluid.Types.Dynamics.SteadyState,
    m_flow_nominal=m_flow_nominal,
    dp_nominal=dp_nominal)
    "MBL speed-controlled pump candidate";

  Buildings.Fluid.FixedResistances.PressureDrop systemResistance(
    redeclare package Medium = Medium,
    m_flow_nominal=m_flow_nominal,
    dp_nominal=dp_system_nominal)
    "Simple system curve represented as nominal pressure drop";

  Modelica.Blocks.Sources.RealExpression speedCommand(y=y_s)
    "Connector wrapper for clamped normalized speed";

equation
  y_s = min(max(y_in, y_min), y_max);
  connect(source.ports[1], pump.port_a);
  connect(pump.port_b, systemResistance.port_a);
  connect(systemResistance.port_b, sink.ports[1]);
  connect(speedCommand.y, pump.y);
  P_s = P_scale * pump.P;
  m_flow_s = pump.m_flow;
  dp_s = pump.dpMachine;
  head_s = dp_s / (rho_nominal * g);

annotation(
  experiment(StartTime=0, StopTime=86400, Interval=300, Tolerance=1e-6),
  Documentation(info="<html><p>FMU wrapper draft for Site A pump auto-modelling using Buildings.Fluid.Movers.SpeedControlled_y with a simple system resistance. Pump head is inferred; Site A currently has no measured pump head/DP for validation.</p></html>"));
end SiteAPumpMblSpeedSystemCurve;
