//  SMESH  SMESH_MeshVSLink : Connection of SMESH with MeshVS from OCC 
//
//  Copyright (C) 2003  OPEN CASCADE, EADS/CCR, LIP6, CEA/DEN,
//  CEDRAT, EDF R&D, LEG, PRINCIPIA R&D, BUREAU VERITAS
//
//  This library is free software; you can redistribute it and/or
//  modify it under the terms of the GNU Lesser General Public
//  License as published by the Free Software Foundation; either
//  version 2.1 of the License.
//
//  This library is distributed in the hope that it will be useful,
//  but WITHOUT ANY WARRANTY; without even the implied warranty of
//  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
//  Lesser General Public License for more details.
//
//  You should have received a copy of the GNU Lesser General Public
//  License along with this library; if not, write to the Free Software
//  Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307 USA
//
// See http://www.salome-platform.org/ or email : webmaster.salome@opencascade.com
//
// File      : SMESH_MeshVSLink.cxx
// Created   : Mon Dec 1 09:00:00 2008
// Author    : Sioutis Fotios
// Module    : SMESH

// #include <SMESH_MeshVSLink.jxx>

// #ifndef _Standard_TypeMismatch_HeaderFile
// #include <Standard_TypeMismatch.hxx>
// #endif

#ifndef _Standard_Version_HeaderFile
#include <Standard_Version.hxx>
#endif

#if OCC_VERSION_HEX < 0x070000

const Handle(Standard_Type)& SMESH_MeshVSLink::DynamicType() const 
{ 
   return STANDARD_TYPE(SMESH_MeshVSLink) ; 
}

