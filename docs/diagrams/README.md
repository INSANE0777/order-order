# Diagrams

Editable draw.io sources and their PNG exports, used by
`docs/CBCA301_Milestone2_Design_Addendum.docx`.

| file | what it shows |
|---|---|
| `use-case.drawio` | actors, use cases, the seven checks a verification includes |
| `dfd-level-0.drawio` | context diagram: what crosses the system boundary |
| `dfd-level-1.drawio` | five processes over five data stores |
| `class-diagram.drawio` | the SQLite data spine (judgment → version → paragraph; brief → citation → verdict) |
| `sequence-verify.drawio` | one brief through the verification graph, with the model's two messages |

To change a label or a box, edit the `.drawio` file and re-export; do not edit the PNG.

```powershell
# draw.io desktop, portable copy kept on A: so nothing installs to C:
& A:\Order\tools\drawio\draw.io.exe -x -f png --width 2000 -b 10 `
    -o docs\diagrams\use-case.png docs\diagrams\use-case.drawio
```

The `.drawio` files open directly in draw.io desktop or at app.diagrams.net.
