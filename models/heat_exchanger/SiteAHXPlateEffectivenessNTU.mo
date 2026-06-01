model SiteAHXPlateEffectivenessNTU
  package Medium1 = Buildings.Media.Water "CHW side";
  package Medium2 = Buildings.Media.Water "CDW side";

  parameter String table_path = "HX_01_fmu_table.txt" annotation(Evaluate=false);
  parameter Modelica.Units.SI.MassFlowRate m1_flow_nominal = 100.0 annotation(Evaluate=false);
  parameter Modelica.Units.SI.MassFlowRate m2_flow_nominal = 120.0 annotation(Evaluate=false);
  parameter Modelica.Units.SI.PressureDifference dp1_nominal = 0.0 annotation(Evaluate=false);
  parameter Modelica.Units.SI.PressureDifference dp2_nominal = 0.0 annotation(Evaluate=false);
  parameter Modelica.Units.SI.HeatFlowRate Q_flow_nominal = 1000000.0 annotation(Evaluate=false);
  parameter Modelica.Units.SI.Temperature T_a1_nominal = 295.15 annotation(Evaluate=false);
  parameter Modelica.Units.SI.Temperature T_b1_nominal = 290.15 annotation(Evaluate=false);
  parameter Modelica.Units.SI.Temperature T_a2_nominal = 285.15 annotation(Evaluate=false);
  parameter Modelica.Units.SI.Temperature T_b2_nominal = 290.15 annotation(Evaluate=false);
  parameter Real n1(min=0, max=1) = 0.8 annotation(Evaluate=false);
  parameter Real n2(min=0, max=1) = 0.8 annotation(Evaluate=false);
  parameter Real r_nominal(min=0) = 1.0 annotation(Evaluate=false);
  parameter Real cpWat(unit="J/(kg.K)") = 4186.0 annotation(Evaluate=false);

  Modelica.Blocks.Sources.CombiTimeTable tab(
    tableOnFile=true,
    tableName="HX_data",
    fileName=table_path,
    columns=2:14,
    smoothness=Modelica.Blocks.Types.Smoothness.ConstantSegments,
    extrapolation=Modelica.Blocks.Types.Extrapolation.HoldLastPoint);
  Modelica.Blocks.Sources.RealExpression T1InK(y=tab.y[1] + 273.15);
  Modelica.Blocks.Sources.RealExpression T2InK(y=tab.y[3] + 273.15);
  Modelica.Blocks.Sources.RealExpression m1Flow(y=max(0.0, tab.y[5]));
  Modelica.Blocks.Sources.RealExpression m2Flow(y=max(0.0, tab.y[6]));

  Buildings.Fluid.Sources.MassFlowSource_T sou1(
    redeclare package Medium = Medium1,
    use_m_flow_in=true,
    use_T_in=true,
    nPorts=1);
  Buildings.Fluid.Sources.Boundary_pT sin1(
    redeclare package Medium = Medium1,
    nPorts=1);
  Buildings.Fluid.Sources.MassFlowSource_T sou2(
    redeclare package Medium = Medium2,
    use_m_flow_in=true,
    use_T_in=true,
    nPorts=1);
  Buildings.Fluid.Sources.Boundary_pT sin2(
    redeclare package Medium = Medium2,
    nPorts=1);

  Buildings.Fluid.HeatExchangers.PlateHeatExchangerEffectivenessNTU hex(
    redeclare package Medium1 = Medium1,
    redeclare package Medium2 = Medium2,
    allowFlowReversal1=false,
    allowFlowReversal2=false,
    m1_flow_nominal=m1_flow_nominal,
    m2_flow_nominal=m2_flow_nominal,
    dp1_nominal=dp1_nominal,
    dp2_nominal=dp2_nominal,
    configuration=Buildings.Fluid.Types.HeatExchangerConfiguration.CounterFlow,
    use_Q_flow_nominal=true,
    Q_flow_nominal=Q_flow_nominal,
    T_a1_nominal=T_a1_nominal,
    T_b1_nominal=T_b1_nominal,
    T_a2_nominal=T_a2_nominal,
    T_b2_nominal=T_b2_nominal,
    n1=n1,
    n2=n2,
    r_nominal=r_nominal);

  Buildings.Fluid.Sensors.TemperatureTwoPort senT1(
    redeclare package Medium = Medium1,
    m_flow_nominal=m1_flow_nominal);
  Buildings.Fluid.Sensors.TemperatureTwoPort senT2(
    redeclare package Medium = Medium2,
    m_flow_nominal=m2_flow_nominal);

  Modelica.Blocks.Interfaces.RealOutput T1Out_m(unit="K");
  Modelica.Blocks.Interfaces.RealOutput T1Out_s(unit="K");
  Modelica.Blocks.Interfaces.RealOutput T2Out_m(unit="K");
  Modelica.Blocks.Interfaces.RealOutput T2Out_s(unit="K");
  Modelica.Blocks.Interfaces.RealOutput Q_m(unit="W");
  Modelica.Blocks.Interfaces.RealOutput Q_s(unit="W");
  Modelica.Blocks.Interfaces.RealOutput m1_flow_m(unit="kg/s");
  Modelica.Blocks.Interfaces.RealOutput m2_flow_m(unit="kg/s");
  Modelica.Blocks.Interfaces.RealOutput eps_m(unit="1");
  Modelica.Blocks.Interfaces.RealOutput eps_s(unit="1");
  Modelica.Blocks.Interfaces.RealOutput dT_lm_m(unit="K");
  Modelica.Blocks.Interfaces.RealOutput dT_lm_s(unit="K");

equation
  connect(T1InK.y, sou1.T_in);
  connect(T2InK.y, sou2.T_in);
  connect(m1Flow.y, sou1.m_flow_in);
  connect(m2Flow.y, sou2.m_flow_in);
  connect(sou1.ports[1], hex.port_a1);
  connect(hex.port_b1, senT1.port_a);
  connect(senT1.port_b, sin1.ports[1]);
  connect(sou2.ports[1], hex.port_a2);
  connect(hex.port_b2, senT2.port_a);
  connect(senT2.port_b, sin2.ports[1]);

  T1Out_m = tab.y[2] + 273.15;
  T1Out_s = senT1.T;
  T2Out_m = tab.y[4] + 273.15;
  T2Out_s = senT2.T;
  Q_m = tab.y[7];
  Q_s = max(0.0, tab.y[5]) * cpWat * ((tab.y[1] + 273.15) - senT1.T);
  m1_flow_m = tab.y[5];
  m2_flow_m = tab.y[6];
  eps_m = tab.y[10];
  eps_s = Q_s / max(1.0, min(tab.y[5], tab.y[6]) * cpWat * abs(tab.y[1] - tab.y[3]));
  dT_lm_m = tab.y[11];
  dT_lm_s = dT_lm_m;

annotation(
  experiment(StartTime=0, StopTime=3600, Interval=300, Tolerance=1e-6),
  Documentation(info="<html><p>Site A water-water heat exchanger wrapper using Buildings.Fluid.HeatExchangers.PlateHeatExchangerEffectivenessNTU. Table inputs are measured inlet temperatures and measured mass flows only; measured outlet temperatures are echoed only for scoring outputs.</p></html>"));
end SiteAHXPlateEffectivenessNTU;
