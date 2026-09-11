# OpenFloodAI Community Feedback

This page collects simple ideas shared by the community about flood safety, warning systems, technology, preparedness, and public data in Nepal.

It is an early discussion page. It is not an official emergency guide.

## Why This Page Exists

OpenFloodAI should not be only an AI model.

A practical flood-safety system may combine:

- cameras
- sensors
- alerts
- public data
- training
- safe places
- government systems
- human review

Simple example: a camera can help show what is happening at one place, but people still need a safe route, a trusted warning process, and a plan for what to do next.

## Sensors And IoT Devices

Sensors can measure river level, rainfall, soil moisture, ground movement, and device health.

IoT means these devices can automatically send measurements to another system.

Simple example: think of a ruler beside a river. A person can see the water rise from 1 meter to 2 meters. A digital sensor can measure the same change automatically and send it to a computer.

For OpenFloodAI: a camera may show that the river looks much higher, while a sensor may show that the water rose 70 cm in 20 minutes. Combining both can give stronger evidence.

## Sirens, Alerts, Alarms, And Mobile Apps

Detection is useful only if warnings reach people.

Possible channels include:

- sirens
- SMS
- mobile apps
- phone calls
- radio
- community volunteers
- dashboards

Simple example: a smoke detector does not stop a fire. It notices danger and warns people. Flood alerts work the same way.

For OpenFloodAI: during testing, the system can create an alert candidate with evidence. A human or authorized system can verify it before any public warning is sent.

## Training, Drills, And Safe Infrastructure

Technology alone cannot keep people safe.

Communities need to know:

- what an alarm means
- where to go
- what to do when power or mobile networks fail

Safe infrastructure may include high ground, parks, elevated platforms, stairs, evacuation routes, assembly points, and shelters.

Simple example: schools have fire alarms, but students also practice fire drills. In the same way, a village should know: "When this flood siren sounds, follow this route to this safe high-ground area."

Another suggestion is to place clear public boards in flood-affected and landslide-affected areas. These boards should use simple language and local symbols so people know the danger area and what to do.

The boards could show:

- this area may flood or have landslides
- where the safe route starts
- where the nearest safe place or assembly point is
- what to do when a siren, SMS, or official warning is received
- emergency contact numbers approved by local authorities

Simple example: near a river path, a board might say, "Flood risk area. If water rises or siren sounds, move to the school ground using the marked route." This helps visitors, children, and people without phones understand what to do.

Community feedback: emergency preparedness should be practiced regularly, not only discussed after a disaster.

One suggestion is that schools and workplaces should run four basic safety drills:

1. Fire drill
2. Landslide and flood drill
3. Earthquake drill
4. General emergency drill

Simple example: if students already know where to gather during a fire drill, they should also know where to go during a flood or earthquake drill.

Another suggestion is that disaster work should be delegated clearly. One person or one office cannot be everywhere during an emergency. Central government and parliament can focus on national plans, laws, funding, and standards. Provincial and local governments can adapt those plans for their own geography, rivers, hills, roads, schools, and communities.

Simple example: a mountain district may need stronger landslide planning, while a river-side town may need clearer flood routes and siren practice. The national plan can set the standard, but local teams need room to adjust it.

## AI Tool Access From Nepal

Some contributors may ask whether tools like Claude or other AI services can be used from Nepal.

Claude access and payment support can change over time. Contributors should check the official provider page and use only official websites.

Simple example: it is like paying for an international streaming service. The service may be available, but your card or payment method also needs to support international online payments.

For OpenFloodAI contributors: nobody should need a paid AI subscription just to contribute. The project should support free or low-cost tools wherever practical.

Reference:

- [Anthropic supported countries and regions](https://www.anthropic.com/supported-countries)

## What Does Nepal Already Have?

Nepal is not starting from zero. Existing systems already provide disaster and hydrology information.

Examples to research:

- DHM: rainfall, river, and hydrology information.
- BIPAD Portal: integrated disaster-information platform.
- BIPAD Realtime: rainfall and river data sourced from DHM.
- BIPAD IBF: impact-based forecasting support.
- BIPAD API: public categories such as rain stations, river stations, weather, precipitation, and streamflow.

Simple example: if the government already has a thermometer, OpenFloodAI should not build another thermometer. We should ask what useful information cameras or sensors can add.

## Where Might The Gap Be?

The right question is not "what is wrong with the current system?"

The better question is:

```text
What useful local information may still be missing?
```

| What may exist | Possible gap to investigate | Possible OpenFloodAI role |
| --- | --- | --- |
| River gauges and rainfall stations | Some small rivers or vulnerable places may have limited instrumentation. | Low-cost cameras or sensors at selected locations. |
| Forecasts and dashboards | Very local visual evidence may help during fast-changing events. | Camera-based observation and rate-of-change evidence. |
| Government alerts | Last-mile communication and local preparedness may vary. | Explore interoperability and community-warning support. |
| Historical records | Useful data may be spread across systems and formats. | Combine permitted public datasets for research and testing. |

Important: these are research questions, not conclusions. OpenFloodAI should validate them with government agencies, researchers, responders, and local communities.

## How Can We Use Publicly Available Data?

Public data can help us:

- understand river behavior
- choose test locations
- compare camera observations with official measurements
- study past disasters
- test whether OpenFloodAI adds value

Simple example: if our camera says a river started rising quickly at 2:10 PM, and a nearby official river station also shows a sharp rise around that time, we can compare both records as evidence.

Useful steps:

- Find available river, rainfall, streamflow, station, and disaster-event data.
- Check source, license, update frequency, and reliability.
- Match public measurements with camera or video time and location.
- Build historical replay datasets.
- Compare OpenFloodAI detections with trusted measurements and documented events.
- Document missing data instead of guessing.

## Big Picture

```text
Camera + Sensors + Government/Public Data
-> Analysis
-> Risk Assessment
-> Alert Candidate
-> Community Action
```

AI is only one part.

Communication, training, safe infrastructure, trusted public agencies, testing, and human decision-making are equally important.

## Useful Links

- [BIPAD Portal](https://bipadportal.gov.np/)
- [BIPAD Realtime](https://bipadportal.gov.np/realtime/)
- [BIPAD Impact-Based Forecasting](https://bipadportal.gov.np/ibf/)
- [BIPAD API](https://bipadportal.gov.np/api/)
- [Anthropic supported countries and regions](https://www.anthropic.com/supported-countries)

This page is for community feedback and research planning. It is not an official emergency or evacuation guide.
